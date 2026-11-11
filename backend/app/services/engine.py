"""Reminder engine: one pass marks missed follow-ups and sends due reminders for every active hospital.

Safe to run from several workers at once: due rows are claimed with SELECT … FOR UPDATE SKIP LOCKED and
committed as "processing" before any API call, so two workers can never pick up the same reminder.
"""
import logging
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.clock import hospital_now, utcnow
from app.models import Hospital, ReminderSchedule, SystemSetting, WhatsAppMessage
from app.services import followups
from app.services.whatsapp import sender

log = logging.getLogger("tectha.engine")
BATCH = 50


def run_once(db: Session, hospital_ids: list | None = None) -> dict:
    q = select(Hospital).where(Hospital.is_active.is_(True), Hospital.deleted_at.is_(None))
    if hospital_ids:
        q = q.where(Hospital.id.in_(hospital_ids))
    totals = {"hospitals": 0, "missed_marked": 0, "processed": 0, "sent": 0, "simulated": 0, "skipped": 0,
              "failed": 0, "retrying": 0, "recovered": 0}
    for hospital in db.scalars(q).all():
        totals["hospitals"] += 1
        stats = run_hospital(db, hospital)
        for k, v in stats.items():
            totals[k] = totals.get(k, 0) + v
    _heartbeat(db, totals)
    return totals


def run_hospital(db: Session, hospital: Hospital) -> dict:
    stats = {"missed_marked": 0, "processed": 0, "sent": 0, "simulated": 0, "skipped": 0, "failed": 0,
             "retrying": 0, "recovered": 0}
    now = hospital_now(hospital)
    stats["recovered"] = recover_stale(db, hospital, now)
    stats["missed_marked"] = followups.mark_missed(db, hospital, now)
    db.commit()
    while True:
        claimed = claim_due(db, hospital, now)
        if not claimed:
            break
        for rid in claimed:
            r = db.get(ReminderSchedule, rid)
            try:
                result = sender.process_reminder(db, hospital, r, hospital_now(hospital))
                db.commit()
            except Exception as exc:  # never let one bad row stop the run; record it instead
                db.rollback()
                log.exception("Reminder %s failed", rid)
                r = db.get(ReminderSchedule, rid)
                r.status, r.last_error, r.processed_at = "failed", f"Internal error: {exc}", now
                db.commit()
                result = "failed"
            stats["processed"] += 1
            key = "retrying" if result == "pending" else result
            stats[key] = stats.get(key, 0) + 1
        if len(claimed) < BATCH:
            break
    return stats


def claim_due(db: Session, hospital: Hospital, now) -> list:
    rows = db.scalars(
        select(ReminderSchedule)
        .where(ReminderSchedule.hospital_id == hospital.id, ReminderSchedule.status == "pending",
               ReminderSchedule.due_at <= now,
               or_(ReminderSchedule.next_attempt_at.is_(None), ReminderSchedule.next_attempt_at <= now))
        .order_by(ReminderSchedule.due_at)
        .limit(BATCH)
        .with_for_update(skip_locked=True)
    ).all()
    for r in rows:
        r.status, r.claimed_at = "processing", now
    ids = [r.id for r in rows]
    db.commit()
    return ids


def recover_stale(db: Session, hospital: Hospital, now) -> int:
    """A worker died mid-send. We can't know whether WhatsApp accepted the message, so we don't resend
    automatically; the reminder is marked failed with an explanation and staff may retry it."""
    cutoff = now - timedelta(minutes=settings.PROCESSING_STALE_MINUTES)
    rows = db.scalars(select(ReminderSchedule).where(
        ReminderSchedule.hospital_id == hospital.id, ReminderSchedule.status == "processing",
        ReminderSchedule.claimed_at < cutoff).with_for_update(skip_locked=True)).all()
    for r in rows:
        ok = db.scalar(select(WhatsAppMessage).where(
            WhatsAppMessage.reminder_id == r.id, WhatsAppMessage.status.in_(sender.SUCCESS_STATUSES)).limit(1))
        r.processed_at = now
        if ok:
            r.status = "simulated" if ok.is_simulated else "sent"
        else:
            r.status = "failed"
            r.last_error = "Sending was interrupted. Check whether the patient received it before retrying."
    return len(rows)


def _heartbeat(db: Session, totals: dict) -> None:
    row = db.get(SystemSetting, "worker_heartbeat")
    value = {"at": utcnow().isoformat(), "last_run": totals}
    if row is None:
        db.add(SystemSetting(key="worker_heartbeat", value=value))
    else:
        row.value = value
    db.commit()
