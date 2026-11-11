"""Public booking API. Exposes only the hospital's public profile and free/taken slot flags — never
patient information. The booking response shows only what the patient just typed."""
import uuid
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import hospital_now, local_today, to_local
from app.core.deps import client_ip
from app.core.errors import ServiceError
from app.core.ratelimit import booking_limiter, public_read_limiter
from app.db import get_db
from app.models import Doctor, DoctorAvailability, Hospital
from app.services import booking, patients
from app.services.audit import audit
from app.services.slots import bookable_dates, day_slots

router = APIRouter(prefix="/api/public", tags=["public"])


def _hospital(db: Session, slug: str) -> Hospital:
    h = db.scalar(select(Hospital).where(Hospital.slug == slug.lower(), Hospital.deleted_at.is_(None)))
    if h is None or not h.is_active:
        raise HTTPException(404, "This booking page is not available.")
    return h


def _doctors(db: Session, h: Hospital) -> list[Doctor]:
    return list(db.scalars(select(Doctor).where(
        Doctor.hospital_id == h.id, Doctor.is_active.is_(True), Doctor.deleted_at.is_(None),
        Doctor.id.in_(select(DoctorAvailability.doctor_id))).order_by(Doctor.name)).all())


@router.get("/hospitals/{slug}")
def hospital_profile(slug: str, request: Request, db: Session = Depends(get_db)):
    public_read_limiter.check(client_ip(request) or "?")
    h = _hospital(db, slug)
    return {
        "name": h.name, "slug": h.slug, "address": h.address, "phone": h.phone, "default_language": h.default_language,
        "booking_horizon_days": h.booking_horizon_days, "today": local_today(h).isoformat(), "timezone": h.timezone,
        "is_demo": h.is_demo,
        "doctors": [{"id": str(d.id), "name": d.name, "specialty": d.specialty} for d in _doctors(db, h)],
    }


@router.get("/hospitals/{slug}/dates")
def open_dates(slug: str, request: Request, doctor_id: uuid.UUID, db: Session = Depends(get_db)):
    public_read_limiter.check(client_ip(request) or "?")
    h = _hospital(db, slug)
    doctor = booking.get_doctor(db, h, doctor_id)
    return {"dates": bookable_dates(db, h, doctor)}


@router.get("/hospitals/{slug}/slots")
def slots(slug: str, request: Request, doctor_id: uuid.UUID, on: date = Query(alias="date"),
          db: Session = Depends(get_db)):
    public_read_limiter.check(client_ip(request) or "?")
    h = _hospital(db, slug)
    doctor = booking.get_doctor(db, h, doctor_id)
    today = local_today(h)
    if on < today or on > today + timedelta(days=h.booking_horizon_days):
        return {"date": on.isoformat(), "slots": []}
    return {"date": on.isoformat(), "slots": [
        {"start_at": s.start_at.isoformat(), "time": to_local(h, s.start_at).strftime("%H:%M"), "available": s.available}
        for s in day_slots(db, h, doctor, on)]}


class BookingIn(BaseModel):
    doctor_id: uuid.UUID
    start_at: datetime
    full_name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=6, max_length=24)
    language: str = Field(default="en", pattern="^(en|ta)$")
    whatsapp_consent: bool = False
    website: str | None = Field(default=None, max_length=200)  # honeypot: humans never fill this


@router.post("/hospitals/{slug}/appointments", status_code=201)
def book(slug: str, body: BookingIn, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request) or "?"
    booking_limiter.check(ip)
    if body.website:
        raise HTTPException(400, "Booking could not be completed.")
    h = _hospital(db, slug)
    doctor = booking.get_doctor(db, h, body.doctor_id)
    try:
        patient = patients.find_or_create_patient(
            db, h, full_name=body.full_name, phone=body.phone, language=body.language,
            whatsapp_consent=body.whatsapp_consent, consent_source="booking_form", is_test=h.is_demo)
        appt = booking.book_appointment(db, h, patient=patient, doctor=doctor, start_at=body.start_at, source="online")
        booking.supersede_reschedule_requests(db, h, patient, appt)
    except ServiceError:
        db.rollback()
        raise
    audit(db, "appointment.booked_online", hospital_id=h.id, entity_type="appointment", entity_id=appt.id, ip=ip)
    db.commit()
    local = to_local(h, appt.start_at)
    return {
        "reference": appt.reference, "hospital": h.name, "hospital_phone": h.phone, "address": h.address,
        "doctor": doctor.name, "date": local.date().isoformat(), "time": local.strftime("%H:%M"),
        "start_at": appt.start_at.isoformat(), "patient_name": patient.full_name,
        "whatsapp_reminder": bool(patient.whatsapp_opt_in),
        "booked_at": hospital_now(h).isoformat(),
    }
