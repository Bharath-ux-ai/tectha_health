"""Reminder scheduling rules.

* Appointment: the day before the visit, at the hospital's appointment reminder time (default 18:00).
  If the booking is made after that moment but before the visit day, the reminder is due immediately.
  Same-day bookings get no reminder.
* Follow-up: 7 days and 3 days before the follow-up date, at the hospital's follow-up reminder time.
  A reminder whose moment has already passed when the follow-up is saved is recorded as skipped —
  it is never sent late.

Every reminder has an idempotency key of (target, target date, kind). Re-saving or moving a date back
can never produce a second reminder for the same moment.
"""
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.clock import hospital_now, local_dt, local_today, to_local
from app.models import Appointment, FollowUp, Hospital, ReminderSchedule

FOLLOWUP_OFFSETS = (("followup_7d", 7), ("followup_3d", 3))


def appointment_key(appt: Appointment) -> str:
    return f"appt:{appt.id}:{int(appt.start_at.timestamp())}:day_before"


def followup_key(fu: FollowUp, kind: str) -> str:
    return f"fu:{fu.id}:{fu.due_date.isoformat()}:{kind}"


def cancel_pending(db: Session, *, appointment_id=None, follow_up_id=None, keep_keys: tuple[str, ...] = ()) -> int:
    q = update(ReminderSchedule).where(ReminderSchedule.status == "pending")
    if appointment_id is not None:
        q = q.where(ReminderSchedule.appointment_id == appointment_id)
    if follow_up_id is not None:
        q = q.where(ReminderSchedule.follow_up_id == follow_up_id)
    if keep_keys:
        q = q.where(ReminderSchedule.idempotency_key.not_in(keep_keys))
    return db.execute(q.values(status="cancelled", skip_reason="target_changed")).rowcount or 0


def _activate(r: ReminderSchedule, due: datetime, now: datetime, *, late_policy: str, skip_reason: str) -> None:
    r.due_at = due
    r.status = "pending"
    r.skip_reason = None
    r.next_attempt_at = None
    if due <= now:
        if late_policy == "now":
            r.due_at = now
        else:
            r.status = "skipped"
            r.skip_reason = skip_reason


def schedule_appointment_reminder(db: Session, hospital: Hospital, appt: Appointment,
                                  now: datetime | None = None) -> ReminderSchedule | None:
    now = now or hospital_now(hospital)
    key = appointment_key(appt)
    cancel_pending(db, appointment_id=appt.id, keep_keys=(key,))
    if appt.status not in ("booked", "confirmed") or appt.start_at <= now:
        cancel_pending(db, appointment_id=appt.id)
        return None
    local_start = to_local(hospital, appt.start_at)
    due = local_dt(hospital, local_start.date() - timedelta(days=1), hospital.appointment_reminder_time)
    late_policy = "now" if local_start.date() > local_today(hospital, now) else "skip"

    existing = db.scalar(select(ReminderSchedule).where(ReminderSchedule.idempotency_key == key))
    if existing:
        if existing.status == "cancelled":
            _activate(existing, due, now, late_policy=late_policy, skip_reason="same_day_booking")
        return existing
    r = ReminderSchedule(hospital_id=hospital.id, kind="appointment_day_before", appointment_id=appt.id,
                         patient_id=appt.patient_id, idempotency_key=key, due_at=due)
    _activate(r, due, now, late_policy=late_policy, skip_reason="same_day_booking")
    db.add(r)
    return r


def schedule_followup_reminders(db: Session, hospital: Hospital, fu: FollowUp,
                                now: datetime | None = None) -> list[ReminderSchedule]:
    now = now or hospital_now(hospital)
    keys = tuple(followup_key(fu, kind) for kind, _ in FOLLOWUP_OFFSETS)
    cancel_pending(db, follow_up_id=fu.id, keep_keys=keys)
    if fu.status != "scheduled":
        cancel_pending(db, follow_up_id=fu.id)
        return []
    out = []
    for kind, days in FOLLOWUP_OFFSETS:
        key = followup_key(fu, kind)
        due = local_dt(hospital, fu.due_date - timedelta(days=days), hospital.followup_reminder_time)
        existing = db.scalar(select(ReminderSchedule).where(ReminderSchedule.idempotency_key == key))
        if existing:
            if existing.status == "cancelled":
                _activate(existing, due, now, late_policy="skip", skip_reason="window_passed")
            out.append(existing)
            continue
        r = ReminderSchedule(hospital_id=hospital.id, kind=kind, follow_up_id=fu.id, patient_id=fu.patient_id,
                             idempotency_key=key, due_at=due)
        _activate(r, due, now, late_policy="skip", skip_reason="window_passed")
        db.add(r)
        out.append(r)
    return out


def reschedule_for_hospital_settings(db: Session, hospital: Hospital) -> int:
    """Reminder send times changed: move the due time of every still-pending reminder."""
    now = hospital_now(hospital)
    pending = db.scalars(select(ReminderSchedule).where(
        ReminderSchedule.hospital_id == hospital.id, ReminderSchedule.status == "pending",
        ReminderSchedule.attempts == 0)).all()
    for r in pending:
        if r.appointment_id:
            appt = db.get(Appointment, r.appointment_id)
            d = to_local(hospital, appt.start_at).date() - timedelta(days=1)
            due = local_dt(hospital, d, hospital.appointment_reminder_time)
            r.due_at = max(due, now) if to_local(hospital, appt.start_at).date() > local_today(hospital, now) else due
        else:
            fu = db.get(FollowUp, r.follow_up_id)
            days = dict(FOLLOWUP_OFFSETS)[r.kind]
            r.due_at = local_dt(hospital, fu.due_date - timedelta(days=days), hospital.followup_reminder_time)
    return len(pending)
