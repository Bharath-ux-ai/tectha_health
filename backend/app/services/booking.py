"""Appointment booking, status changes and rescheduling."""
import secrets
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import hospital_now, local_day_bounds, local_today, to_local
from app.core.errors import Conflict, NotFound, ServiceError
from app.models import ACTIVE_APPOINTMENT_STATUSES, Appointment, Doctor, Hospital, Patient
from app.services import reminders
from app.services.slots import find_slot

REF_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "booked": {"confirmed", "reschedule_requested", "cancelled", "completed", "no_show"},
    "confirmed": {"reschedule_requested", "cancelled", "completed", "no_show"},
    "reschedule_requested": {"confirmed", "cancelled", "completed", "no_show"},
    "no_show": {"completed"},  # patient arrived late; staff corrects the record
    "completed": set(),
    "cancelled": set(),
    "rescheduled": set(),
}


def new_reference() -> str:
    return "TT-" + "".join(secrets.choice(REF_ALPHABET) for _ in range(6))


def get_doctor(db: Session, hospital: Hospital, doctor_id: uuid.UUID) -> Doctor:
    doctor = db.get(Doctor, doctor_id)
    if not doctor or doctor.hospital_id != hospital.id or doctor.deleted_at or not doctor.is_active:
        raise NotFound("Doctor not found.")
    return doctor


def book_appointment(
    db: Session,
    hospital: Hospital,
    *,
    patient: Patient,
    doctor: Doctor,
    start_at: datetime,
    source: str,
    user_id: uuid.UUID | None = None,
    status: str = "booked",
    follow_up_id: uuid.UUID | None = None,
    lead_minutes: int | None = None,
) -> Appointment:
    now = hospital_now(hospital)
    if start_at.tzinfo is None:
        raise ServiceError("Appointment time must include a timezone.")
    local_date = to_local(hospital, start_at).date()
    today = local_today(hospital, now)
    if local_date < today:
        raise ServiceError("That date has already passed.")
    if local_date > today + timedelta(days=hospital.booking_horizon_days) and source == "online":
        raise ServiceError(f"Bookings open up to {hospital.booking_horizon_days} days ahead.")
    slot = find_slot(db, hospital, doctor, start_at, lead_minutes=lead_minutes, now=now)
    if slot is None:
        raise ServiceError("That time is not part of the doctor's schedule.")
    if not slot.available:
        raise Conflict("That time was just taken. Please pick another slot.", code="slot_taken")

    # One active booking per patient, per doctor, per day — stops accidental double submissions.
    day_start, day_end = local_day_bounds(hospital, local_date)
    dup = db.scalar(select(Appointment).where(
        Appointment.patient_id == patient.id, Appointment.doctor_id == doctor.id,
        Appointment.start_at >= day_start, Appointment.start_at < day_end,
        Appointment.status.in_(ACTIVE_APPOINTMENT_STATUSES)))
    if dup:
        t = to_local(hospital, dup.start_at).strftime("%I:%M %p").lstrip("0")
        raise Conflict(f"{patient.full_name} already has an appointment that day at {t} (ref {dup.reference}).",
                       code="duplicate_booking")

    appt = Appointment(
        hospital_id=hospital.id, patient_id=patient.id, doctor_id=doctor.id, start_at=slot.start_at,
        end_at=slot.end_at, status=status, source=source, booked_by_user_id=user_id, follow_up_id=follow_up_id,
    )
    if status == "confirmed":
        appt.confirmed_at = now
        appt.confirmed_via = "whatsapp" if source == "followup" else "staff"
    for _ in range(5):
        appt.reference = new_reference()
        try:
            with db.begin_nested():
                db.add(appt)
                db.flush()
            break
        except IntegrityError as exc:
            msg = str(exc.orig)
            if "uq_appointments_active_slot" in msg:
                raise Conflict("That time was just taken. Please pick another slot.", code="slot_taken") from exc
            if "reference" not in msg:
                raise
    else:  # pragma: no cover - 31^6 references; collisions this unlucky are not realistic
        raise ServiceError("Could not generate a booking reference. Try again.")

    reminders.schedule_appointment_reminder(db, hospital, appt, now)
    return appt


def supersede_reschedule_requests(db: Session, hospital: Hospital, patient: Patient, new_appt: Appointment) -> int:
    """A patient who asked to reschedule and then books again online: the old booking is marked rescheduled."""
    now = hospital_now(hospital)
    old = db.scalars(select(Appointment).where(
        Appointment.patient_id == patient.id, Appointment.status == "reschedule_requested",
        Appointment.id != new_appt.id, Appointment.start_at > now - timedelta(days=1))).all()
    for appt in old:
        appt.status = "rescheduled"
        appt.rescheduled_to_id = new_appt.id
        appt.cancelled_at = now
        appt.cancel_reason = f"Patient rebooked online ({new_appt.reference})"
        reminders.cancel_pending(db, appointment_id=appt.id)
        if appt.follow_up_id and not new_appt.follow_up_id:
            new_appt.follow_up_id = appt.follow_up_id
    return len(old)


def change_status(db: Session, hospital: Hospital, appt: Appointment, new_status: str, *,
                  reason: str | None = None, via: str = "staff") -> Appointment:
    now = hospital_now(hospital)
    if new_status == appt.status:
        return appt
    if new_status not in ALLOWED_TRANSITIONS.get(appt.status, set()):
        raise ServiceError(f"An appointment that is {appt.status.replace('_', ' ')} can't be marked "
                           f"{new_status.replace('_', ' ')}.")
    if new_status in ("completed", "no_show") and to_local(hospital, appt.start_at).date() > local_today(hospital, now):
        raise ServiceError("You can record the visit outcome on or after the appointment day.")
    if new_status == "confirmed" and appt.start_at <= now - timedelta(hours=12):
        raise ServiceError("This appointment is in the past.")
    appt.status = new_status
    if new_status == "confirmed":
        appt.confirmed_at, appt.confirmed_via = now, via
    elif new_status == "cancelled":
        appt.cancelled_at, appt.cancel_reason = now, (reason or None)
    elif new_status == "completed":
        appt.completed_at = now
    if new_status in ("cancelled", "completed", "no_show", "reschedule_requested"):
        reminders.cancel_pending(db, appointment_id=appt.id)
    if new_status == "completed":
        from app.services.followups import complete_followups_for_visit
        complete_followups_for_visit(db, hospital, appt)
    return appt


def reschedule(db: Session, hospital: Hospital, appt: Appointment, *, doctor: Doctor, start_at: datetime) -> Appointment:
    if appt.status not in ACTIVE_APPOINTMENT_STATUSES:
        raise ServiceError("Only upcoming appointments can be rescheduled.")
    now = hospital_now(hospital)
    if to_local(hospital, start_at).date() < local_today(hospital, now):
        raise ServiceError("That date has already passed.")
    slot = find_slot(db, hospital, doctor, start_at, lead_minutes=0, now=now)
    if slot is None:
        raise ServiceError("That time is not part of the doctor's schedule.")
    same_slot = appt.doctor_id == doctor.id and appt.start_at == slot.start_at
    if not slot.available and not same_slot:
        raise Conflict("That time is already booked. Pick another slot.", code="slot_taken")
    appt.doctor_id = doctor.id
    appt.start_at, appt.end_at = slot.start_at, slot.end_at
    appt.status = "booked"
    appt.confirmed_at = appt.confirmed_via = None
    appt.reschedule_count += 1
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError as exc:
        raise Conflict("That time is already booked. Pick another slot.", code="slot_taken") from exc
    reminders.schedule_appointment_reminder(db, hospital, appt, now)
    return appt
