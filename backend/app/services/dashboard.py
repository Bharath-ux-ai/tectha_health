"""Reception dashboard queries — everything comes from the database, nothing is precomputed."""
from datetime import date, timedelta

from sqlalchemy import func, select, true
from sqlalchemy.orm import Session, selectinload

from app.core.clock import hospital_now, local_day_bounds, local_today
from app.models import (
    ACTIVE_APPOINTMENT_STATUSES, OPEN_FOLLOWUP_STATUSES, Appointment, ContactLog, FollowUp, Hospital, ReminderSchedule,
)
from app.services.followups import attention_for, failed_reminder_followup_ids

MISSED_LOOKBACK_DAYS = 30


def followup_rows(db: Session, hospital: Hospital, fus: list[FollowUp], today: date) -> list[dict]:
    failed = failed_reminder_followup_ids(db, fus)
    ids = [f.id for f in fus]
    last_contact = {}
    if ids:
        for fid, at, outcome in db.execute(
            select(ContactLog.follow_up_id, ContactLog.created_at, ContactLog.outcome)
            .where(ContactLog.follow_up_id.in_(ids)).order_by(ContactLog.created_at)
        ).all():
            last_contact[fid] = {"at": at.isoformat(), "outcome": outcome}
    reminder_state = {}
    if ids:
        for fid, kind, status in db.execute(select(
            ReminderSchedule.follow_up_id, ReminderSchedule.kind, ReminderSchedule.status
        ).where(ReminderSchedule.follow_up_id.in_(ids), ReminderSchedule.status != "cancelled")).all():
            reminder_state.setdefault(fid, {})[kind] = status
    out = []
    for fu in fus:
        att = attention_for(fu, today, fu.id in failed)
        out.append({
            "id": str(fu.id), "due_date": fu.due_date.isoformat(), "status": fu.status,
            "days_to_due": (fu.due_date - today).days,
            "attention": att.level, "attention_reason": att.reason,
            "patient": {"id": str(fu.patient.id), "name": fu.patient.full_name, "phone": fu.patient.phone_e164,
                        "language": fu.patient.preferred_language, "whatsapp_opt_in": fu.patient.whatsapp_opt_in},
            "doctor": fu.doctor.name if fu.doctor else None,
            "booked_appointment_id": str(fu.booked_appointment_id) if fu.booked_appointment_id else None,
            "reminders": reminder_state.get(fu.id, {}),
            "last_contact": last_contact.get(fu.id),
            "note": fu.note,
        })
    rank = {"red": 0, "amber": 1, None: 2}
    out.sort(key=lambda r: (rank[r["attention"]], r["due_date"]))
    return out


def appointment_row(hospital: Hospital, a: Appointment) -> dict:
    from app.core.clock import to_local
    local = to_local(hospital, a.start_at)
    return {
        "id": str(a.id), "reference": a.reference, "start_at": a.start_at.isoformat(),
        "local_date": local.date().isoformat(), "local_time": local.strftime("%H:%M"), "status": a.status,
        "source": a.source, "confirmed_via": a.confirmed_via,
        "patient": {"id": str(a.patient.id), "name": a.patient.full_name, "phone": a.patient.phone_e164,
                    "whatsapp_opt_in": a.patient.whatsapp_opt_in},
        "doctor": {"id": str(a.doctor.id), "name": a.doctor.name},
    }


def dashboard(db: Session, hospital: Hospital, day: date | None = None) -> dict:
    now = hospital_now(hospital)
    today = local_today(hospital, now)
    day = day or today
    start, end = local_day_bounds(hospital, day)
    appts = db.scalars(select(Appointment).options(selectinload(Appointment.patient), selectinload(Appointment.doctor))
                       .where(Appointment.hospital_id == hospital.id, Appointment.start_at >= start,
                              Appointment.start_at < end, Appointment.status != "rescheduled")
                       .order_by(Appointment.start_at)).all()
    counts = {s: 0 for s in ("booked", "confirmed", "reschedule_requested", "cancelled", "completed", "no_show")}
    for a in appts:
        counts[a.status] = counts.get(a.status, 0) + 1

    fu_q = select(FollowUp).options(selectinload(FollowUp.patient), selectinload(FollowUp.doctor)).where(
        FollowUp.hospital_id == hospital.id)
    open_fus = db.scalars(fu_q.where(
        ((FollowUp.status.in_(OPEN_FOLLOWUP_STATUSES)) & (FollowUp.due_date <= today + timedelta(days=14))) |
        ((FollowUp.status == "missed") & (FollowUp.due_date >= today - timedelta(days=MISSED_LOOKBACK_DAYS)))
    ).order_by(FollowUp.due_date)).all()
    rows = followup_rows(db, hospital, open_fus, today)
    attention = [r for r in rows if r["attention"]]
    upcoming = [r for r in rows if not r["attention"] and r["status"] in OPEN_FOLLOWUP_STATUSES]

    past_start, _ = local_day_bounds(hospital, today - timedelta(days=14))
    today_start, _ = local_day_bounds(hospital, today)
    needs_outcome = db.scalars(select(Appointment).options(selectinload(Appointment.patient), selectinload(Appointment.doctor))
                               .where(Appointment.hospital_id == hospital.id, Appointment.start_at >= past_start,
                                      Appointment.start_at < today_start,
                                      Appointment.status.in_(ACTIVE_APPOINTMENT_STATUSES))
                               .order_by(Appointment.start_at.desc()).limit(25)).all()
    failed_7d = db.scalar(select(func.count()).select_from(ReminderSchedule).where(
        ReminderSchedule.hospital_id == hospital.id, ReminderSchedule.status == "failed",
        (ReminderSchedule.updated_at >= now - timedelta(days=7)) if not hospital.is_demo else true())) or 0
    pending = db.scalar(select(func.count()).select_from(ReminderSchedule).where(
        ReminderSchedule.hospital_id == hospital.id, ReminderSchedule.status == "pending")) or 0
    next_due = db.scalar(select(func.min(ReminderSchedule.due_at)).where(
        ReminderSchedule.hospital_id == hospital.id, ReminderSchedule.status == "pending"))

    return {
        "date": day.isoformat(), "today": today.isoformat(), "now": now.isoformat(),
        "counts": {"total": sum(v for k, v in counts.items()), **counts,
                   "pending_confirmation": counts["booked"] + counts["reschedule_requested"]},
        "appointments": [appointment_row(hospital, a) for a in appts],
        "attention": attention,
        "attention_red": sum(1 for r in attention if r["attention"] == "red"),
        "upcoming_followups": upcoming,
        "needs_outcome": [appointment_row(hospital, a) for a in needs_outcome],
        "reminders": {"failed_recent": failed_7d, "pending": pending,
                      "next_due_at": next_due.isoformat() if next_due else None},
    }
