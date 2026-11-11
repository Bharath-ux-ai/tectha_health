import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api.common import appointment_out, followup_out, message_out
from app.core.clock import local_day_bounds, local_today, to_local
from app.core.deps import CurrentUser, client_ip, get_owned, require_hospital
from app.db import get_db
from app.models import Appointment, FollowUp, Hospital, Patient, ReminderSchedule, WhatsAppMessage
from app.services import booking, patients
from app.services.audit import audit
from app.services.slots import day_slots

router = APIRouter(prefix="/api/appointments", tags=["appointments"])


def _load(db: Session, current: CurrentUser, appt_id: uuid.UUID) -> tuple[Hospital, Appointment]:
    h = db.get(Hospital, current.hospital_id)
    return h, get_owned(db, Appointment, appt_id, h.id, label="Appointment")


@router.get("")
def list_appointments(
    date_from: date | None = None, date_to: date | None = None, status: str | None = None,
    doctor_id: uuid.UUID | None = None, q: str | None = Query(default=None, max_length=80),
    page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=200),
    current: CurrentUser = Depends(require_hospital("appointments:read")), db: Session = Depends(get_db),
):
    h = db.get(Hospital, current.hospital_id)
    today = local_today(h)
    date_from = date_from or today
    date_to = date_to or date_from
    if date_to < date_from:
        date_from, date_to = date_to, date_from
    start, _ = local_day_bounds(h, date_from)
    _, end = local_day_bounds(h, date_to)
    stmt = (select(Appointment).join(Patient, Patient.id == Appointment.patient_id)
            .options(selectinload(Appointment.patient), selectinload(Appointment.doctor))
            .where(Appointment.hospital_id == h.id, Appointment.start_at >= start, Appointment.start_at < end))
    if status:
        if status == "pending":
            stmt = stmt.where(Appointment.status.in_(("booked", "reschedule_requested")))
        else:
            stmt = stmt.where(Appointment.status.in_(status.split(",")))
    else:
        stmt = stmt.where(Appointment.status != "rescheduled")
    if doctor_id:
        stmt = stmt.where(Appointment.doctor_id == doctor_id)
    if q:
        like = f"%{q.strip().lower()}%"
        digits = "".join(c for c in q if c.isdigit())
        conds = [Patient.name_normalized.like(like), func.lower(Appointment.reference).like(like)]
        if len(digits) >= 4:
            conds.append(Patient.phone_e164.like(f"%{digits}%"))
        stmt = stmt.where(or_(*conds))
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = db.scalars(stmt.order_by(Appointment.start_at).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [appointment_out(h, a) for a in rows], "total": total, "page": page, "page_size": page_size,
            "date_from": date_from.isoformat(), "date_to": date_to.isoformat(), "today": today.isoformat()}


@router.get("/slots")
def staff_slots(doctor_id: uuid.UUID, on: date = Query(alias="date"),
                current: CurrentUser = Depends(require_hospital("appointments:read")), db: Session = Depends(get_db)):
    h = db.get(Hospital, current.hospital_id)
    doctor = booking.get_doctor(db, h, doctor_id)
    return {"date": on.isoformat(), "slots": [
        {"start_at": s.start_at.isoformat(), "time": to_local(h, s.start_at).strftime("%H:%M"), "available": s.available}
        for s in day_slots(db, h, doctor, on, lead_minutes=0)]}


class StaffBookingIn(BaseModel):
    doctor_id: uuid.UUID
    start_at: datetime
    full_name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=6, max_length=24)
    language: str = Field(default="en", pattern="^(en|ta)$")
    whatsapp_consent: bool = False  # staff confirms the patient agreed (recorded as verbal consent)


@router.post("", status_code=201)
def register_appointment(body: StaffBookingIn, request: Request,
                         current: CurrentUser = Depends(require_hospital("appointments:write")),
                         db: Session = Depends(get_db)):
    h = db.get(Hospital, current.hospital_id)
    doctor = booking.get_doctor(db, h, body.doctor_id)
    patient = patients.find_or_create_patient(
        db, h, full_name=body.full_name, phone=body.phone, language=body.language,
        whatsapp_consent=True if body.whatsapp_consent else None, consent_source="staff_verbal",
        user_id=current.id, is_test=h.is_demo)
    appt = booking.book_appointment(db, h, patient=patient, doctor=doctor, start_at=body.start_at, source="staff",
                                    user_id=current.id, lead_minutes=0)
    audit(db, "appointment.registered", hospital_id=h.id, user_id=current.id, entity_type="appointment",
          entity_id=appt.id, ip=client_ip(request))
    db.commit()
    db.refresh(appt)
    return appointment_out(h, appt)


@router.get("/{appt_id}")
def get_appointment(appt_id: uuid.UUID, current: CurrentUser = Depends(require_hospital("appointments:read")),
                    db: Session = Depends(get_db)):
    h, appt = _load(db, current, appt_id)
    reminders = db.scalars(select(ReminderSchedule).where(ReminderSchedule.appointment_id == appt.id)
                           .order_by(ReminderSchedule.created_at)).all()
    msgs = db.scalars(select(WhatsAppMessage).where(WhatsAppMessage.reminder_id.in_([r.id for r in reminders]))
                      .order_by(WhatsAppMessage.created_at)).all() if reminders else []
    fus = db.scalars(select(FollowUp).options(selectinload(FollowUp.patient), selectinload(FollowUp.doctor))
                     .where(FollowUp.source_appointment_id == appt.id).order_by(FollowUp.created_at)).all()
    return {**appointment_out(h, appt), "today": local_today(h).isoformat(),
            "reminders": [reminder_out(r) for r in reminders],
            "messages": [message_out(m) for m in msgs],
            "follow_ups": [followup_out(f) for f in fus]}


def reminder_out(r: ReminderSchedule) -> dict:
    return {"id": str(r.id), "kind": r.kind, "due_at": r.due_at.isoformat(), "status": r.status,
            "attempts": r.attempts, "skip_reason": r.skip_reason, "last_error": r.last_error,
            "next_attempt_at": r.next_attempt_at.isoformat() if r.next_attempt_at else None,
            "processed_at": r.processed_at.isoformat() if r.processed_at else None}


class StatusIn(BaseModel):
    status: str = Field(pattern="^(confirmed|reschedule_requested|cancelled|completed|no_show)$")
    reason: str | None = Field(default=None, max_length=300)


@router.post("/{appt_id}/status")
def set_status(appt_id: uuid.UUID, body: StatusIn, request: Request,
               current: CurrentUser = Depends(require_hospital("appointments:write")), db: Session = Depends(get_db)):
    h, appt = _load(db, current, appt_id)
    old = appt.status
    booking.change_status(db, h, appt, body.status, reason=body.reason)
    audit(db, "appointment.status", hospital_id=h.id, user_id=current.id, entity_type="appointment",
          entity_id=appt.id, details={"from": old, "to": body.status}, ip=client_ip(request))
    db.commit()
    return appointment_out(h, appt)


class RescheduleIn(BaseModel):
    doctor_id: uuid.UUID
    start_at: datetime


@router.post("/{appt_id}/reschedule")
def reschedule(appt_id: uuid.UUID, body: RescheduleIn, request: Request,
               current: CurrentUser = Depends(require_hospital("appointments:write")), db: Session = Depends(get_db)):
    h, appt = _load(db, current, appt_id)
    old = appt.start_at.isoformat()
    doctor = booking.get_doctor(db, h, body.doctor_id)
    booking.reschedule(db, h, appt, doctor=doctor, start_at=body.start_at)
    audit(db, "appointment.rescheduled", hospital_id=h.id, user_id=current.id, entity_type="appointment",
          entity_id=appt.id, details={"from": old, "to": appt.start_at.isoformat()}, ip=client_ip(request))
    db.commit()
    db.refresh(appt)
    return appointment_out(h, appt)

