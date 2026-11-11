"""Follow-up scheduling, status changes, attention flags and one-tap booking from a reminder."""
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import hospital_now, local_today, to_local
from app.core.errors import ServiceError
from app.models import (
    ACTIVE_APPOINTMENT_STATUSES, OPEN_FOLLOWUP_STATUSES, Appointment, Doctor, DoctorAvailability, FollowUp, Hospital,
    Patient, ReminderSchedule,
)
from app.services import reminders

FOLLOWUP_MAX_DAYS_AHEAD = 365
# A visit counts as "the follow-up" if it happens no more than this many days before the due date.
EARLY_VISIT_WINDOW_DAYS = 7


def create_followup(db: Session, hospital: Hospital, *, patient: Patient, due_date: date,
                    source_appointment: Appointment | None, doctor_id: uuid.UUID | None, note: str | None,
                    user_id: uuid.UUID | None) -> FollowUp:
    now = hospital_now(hospital)
    today = local_today(hospital, now)
    if due_date <= today:
        raise ServiceError("Pick a follow-up date after today.")
    if due_date > today + timedelta(days=FOLLOWUP_MAX_DAYS_AHEAD):
        raise ServiceError("Follow-up date must be within a year.")
    if source_appointment is not None:
        if source_appointment.patient_id != patient.id:
            raise ServiceError("That appointment belongs to another patient.")
        existing = db.scalar(select(FollowUp).where(
            FollowUp.source_appointment_id == source_appointment.id, FollowUp.status.in_(OPEN_FOLLOWUP_STATUSES)))
        if existing:
            raise ServiceError("This visit already has an open follow-up. Change its date instead.")
        doctor_id = doctor_id or source_appointment.doctor_id
    fu = FollowUp(hospital_id=hospital.id, patient_id=patient.id, due_date=due_date, status="scheduled",
                  source_appointment_id=source_appointment.id if source_appointment else None,
                  doctor_id=doctor_id, note=(note or "").strip() or None, created_by_user_id=user_id)
    db.add(fu)
    db.flush()
    reminders.schedule_followup_reminders(db, hospital, fu, now)
    return fu


def reschedule_followup(db: Session, hospital: Hospital, fu: FollowUp, new_date: date) -> FollowUp:
    now = hospital_now(hospital)
    if fu.status in ("completed", "cancelled"):
        raise ServiceError("This follow-up is closed.")
    if new_date <= local_today(hospital, now):
        raise ServiceError("Pick a follow-up date after today.")
    if fu.booked_appointment_id:
        booked = db.get(Appointment, fu.booked_appointment_id)
        if booked and booked.status in ACTIVE_APPOINTMENT_STATUSES:
            from app.services.booking import change_status
            change_status(db, hospital, booked, "cancelled", reason="Follow-up moved to another date")
        fu.booked_appointment_id = None
    fu.due_date = new_date
    fu.status = "scheduled"
    fu.confirmed_at = fu.missed_at = fu.reschedule_requested_at = None
    fu.reschedule_count += 1
    reminders.schedule_followup_reminders(db, hospital, fu, now)
    return fu


STAFF_STATUS_CHANGES = {"confirmed", "completed", "cancelled", "missed", "scheduled"}


def change_followup_status(db: Session, hospital: Hospital, fu: FollowUp, new_status: str) -> FollowUp:
    now = hospital_now(hospital)
    if new_status not in STAFF_STATUS_CHANGES:
        raise ServiceError("Unknown follow-up status.")
    if fu.status == new_status:
        return fu
    if fu.status in ("completed", "cancelled") and new_status != "scheduled":
        raise ServiceError("This follow-up is closed.")
    if new_status == "completed" and fu.due_date > local_today(hospital, now) + timedelta(days=EARLY_VISIT_WINDOW_DAYS):
        raise ServiceError("A follow-up can be marked completed from a week before its date.")
    if new_status == "scheduled":
        if fu.due_date <= local_today(hospital, now):
            raise ServiceError("Set a new follow-up date to reopen it.")
        fu.status = "scheduled"
        fu.completed_at = fu.missed_at = fu.confirmed_at = None
        reminders.schedule_followup_reminders(db, hospital, fu, now)
        return fu
    fu.status = new_status
    if new_status == "confirmed":
        fu.confirmed_at = now
    elif new_status == "completed":
        fu.completed_at = now
    elif new_status == "missed":
        fu.missed_at = now
    reminders.cancel_pending(db, follow_up_id=fu.id)
    return fu


def complete_followups_for_visit(db: Session, hospital: Hospital, appt: Appointment) -> list[FollowUp]:
    """When a visit is completed, close the patient's follow-ups that this visit fulfils (verifiable outcome)."""
    visit_date = to_local(hospital, appt.start_at).date()
    rows = db.scalars(select(FollowUp).where(
        FollowUp.patient_id == appt.patient_id,
        FollowUp.status.in_(OPEN_FOLLOWUP_STATUSES + ("missed",)),
        FollowUp.due_date <= visit_date + timedelta(days=EARLY_VISIT_WINDOW_DAYS),
        (FollowUp.source_appointment_id.is_(None)) | (FollowUp.source_appointment_id != appt.id),
    )).all()
    now = hospital_now(hospital)
    for fu in rows:
        fu.status = "completed"
        fu.completed_at = now
        fu.completed_appointment_id = appt.id
        reminders.cancel_pending(db, follow_up_id=fu.id)
    if appt.follow_up_id and all(f.id != appt.follow_up_id for f in rows):
        fu = db.get(FollowUp, appt.follow_up_id)
        if fu and fu.status != "completed":
            fu.status, fu.completed_at, fu.completed_appointment_id = "completed", now, appt.id
            reminders.cancel_pending(db, follow_up_id=fu.id)
            rows.append(fu)
    return rows


def mark_missed(db: Session, hospital: Hospital, now: datetime | None = None) -> int:
    now = now or hospital_now(hospital)
    today = local_today(hospital, now)
    rows = db.scalars(select(FollowUp).where(
        FollowUp.hospital_id == hospital.id, FollowUp.status.in_(OPEN_FOLLOWUP_STATUSES),
        FollowUp.due_date < today)).all()
    for fu in rows:
        fu.status = "missed"
        fu.missed_at = now
        reminders.cancel_pending(db, follow_up_id=fu.id)
    return len(rows)


def pick_doctor_for_followup(db: Session, hospital: Hospital, fu: FollowUp) -> Doctor | None:
    if fu.doctor_id:
        doc = db.get(Doctor, fu.doctor_id)
        if doc and doc.is_active and not doc.deleted_at:
            return doc
    return db.scalar(select(Doctor).join(DoctorAvailability, DoctorAvailability.doctor_id == Doctor.id).where(
        Doctor.hospital_id == hospital.id, Doctor.is_active.is_(True), Doctor.deleted_at.is_(None),
        DoctorAvailability.weekday == fu.due_date.weekday()).order_by(Doctor.name).limit(1))


def autobook_followup(db: Session, hospital: Hospital, fu: FollowUp) -> Appointment | None:
    """Patient tapped Confirm on a follow-up reminder: book the first open slot on the follow-up day."""
    from app.services.booking import book_appointment
    from app.services.slots import day_slots

    if fu.booked_appointment_id:
        existing = db.get(Appointment, fu.booked_appointment_id)
        if existing and existing.status in ACTIVE_APPOINTMENT_STATUSES:
            return existing
    doctor = pick_doctor_for_followup(db, hospital, fu)
    if doctor is None:
        return None
    patient = db.get(Patient, fu.patient_id)
    for slot in day_slots(db, hospital, doctor, fu.due_date):
        if not slot.available:
            continue
        try:
            appt = book_appointment(db, hospital, patient=patient, doctor=doctor, start_at=slot.start_at,
                                    source="followup", status="confirmed", follow_up_id=fu.id)
        except ServiceError:
            continue
        fu.booked_appointment_id = appt.id
        return appt
    return None


@dataclass
class Attention:
    level: str | None  # "red" | "amber" | None
    reason: str | None


def attention_for(fu: FollowUp, today: date, failed_reminder: bool) -> Attention:
    if fu.status == "missed" or (fu.status in OPEN_FOLLOWUP_STATUSES and fu.due_date < today):
        return Attention("red", "missed")
    if fu.status == "scheduled":
        if failed_reminder:
            return Attention("red", "reminder_failed")
        # Reminders go out 7 and 3 days before. From two days before the date, silence means "call them".
        if (fu.due_date - today).days <= 2:
            return Attention("red", "no_response")
    if fu.status == "reschedule_requested":
        return Attention("amber", "reschedule_requested")
    if fu.status == "confirmed" and not fu.booked_appointment_id:
        return Attention("amber", "needs_time")
    return Attention(None, None)


def failed_reminder_followup_ids(db: Session, fus: list[FollowUp]) -> set[uuid.UUID]:
    """Follow-ups whose reminder for the *current* date failed permanently."""
    if not fus:
        return set()
    by_id = {f.id: f for f in fus}
    rows = db.execute(select(ReminderSchedule.follow_up_id, ReminderSchedule.idempotency_key).where(
        ReminderSchedule.follow_up_id.in_(list(by_id)), ReminderSchedule.status == "failed")).all()
    return {fid for fid, key in rows if f":{by_id[fid].due_date.isoformat()}:" in key}
