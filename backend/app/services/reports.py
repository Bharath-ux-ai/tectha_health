"""Monthly report, computed only from recorded outcomes.

"Brought back" = distinct patients whose follow-up was completed this month (a recorded visit) AND who
demonstrably received or answered a reminder for that follow-up before the visit: a WhatsApp delivery or
read receipt, or a Confirm/Reschedule tap. A patient who returned without a delivered reminder is counted
separately as "returned without a delivered reminder", not credited to the reminders.
"""
import csv
import io
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import month_bounds
from app.models import Appointment, FollowUp, Hospital, Patient, ReminderSchedule, WhatsAppMessage

DELIVERED = ("delivered", "read")


def _pct(n: int, d: int) -> float | None:
    return round(100.0 * n / d, 1) if d else None


def monthly_report(db: Session, hospital: Hospital, month_start: date) -> dict:
    start, end, first, nxt = month_bounds(hospital, month_start)
    hid = hospital.id

    appt_rows = db.execute(select(Appointment.status, func.count()).where(
        Appointment.hospital_id == hid, Appointment.start_at >= start, Appointment.start_at < end
    ).group_by(Appointment.status)).all()
    by_status = {s: c for s, c in appt_rows}
    total_appts = sum(c for s, c in by_status.items() if s != "rescheduled")
    wa_confirmed = db.scalar(select(func.count()).select_from(Appointment).where(
        Appointment.hospital_id == hid, Appointment.start_at >= start, Appointment.start_at < end,
        Appointment.confirmed_via == "whatsapp")) or 0

    fu_created = db.scalar(select(func.count()).select_from(FollowUp).where(
        FollowUp.hospital_id == hid, FollowUp.created_at >= start, FollowUp.created_at < end)) or 0
    fu_completed = db.scalars(select(FollowUp).where(
        FollowUp.hospital_id == hid, FollowUp.status == "completed",
        FollowUp.completed_at >= start, FollowUp.completed_at < end)).all()
    due_rows = db.execute(select(FollowUp.status, func.count()).where(
        FollowUp.hospital_id == hid, FollowUp.due_date >= first, FollowUp.due_date < nxt
    ).group_by(FollowUp.status)).all()
    due = {s: c for s, c in due_rows}
    due_total = sum(due.values())
    due_completed = due.get("completed", 0)
    due_cancelled = due.get("cancelled", 0)

    # Attribution — evidence per follow-up
    count_simulated = hospital.is_demo
    ok_statuses = DELIVERED + (("simulated",) if count_simulated else ())
    brought_back, without_reminder = [], []
    for fu in fu_completed:
        delivered = db.scalar(select(func.count()).select_from(WhatsAppMessage).join(
            ReminderSchedule, ReminderSchedule.id == WhatsAppMessage.reminder_id).where(
            ReminderSchedule.follow_up_id == fu.id, WhatsAppMessage.direction == "outbound",
            WhatsAppMessage.status.in_(ok_statuses), WhatsAppMessage.sent_at <= fu.completed_at)) or 0
        replied = db.scalar(select(func.count()).select_from(WhatsAppMessage).where(
            WhatsAppMessage.direction == "inbound", WhatsAppMessage.reply_to_message_id.in_(
                select(WhatsAppMessage.id).join(ReminderSchedule, ReminderSchedule.id == WhatsAppMessage.reminder_id)
                .where(ReminderSchedule.follow_up_id == fu.id)))) or 0
        (brought_back if (delivered or replied) else without_reminder).append(fu)
    brought_back_patients = {fu.patient_id for fu in brought_back}

    # Message statistics (outbound reminders attempted this month, by business time)
    msg_time = func.coalesce(WhatsAppMessage.sent_at, WhatsAppMessage.failed_at, WhatsAppMessage.created_at)
    msg_rows = db.execute(select(WhatsAppMessage.status, func.count()).where(
        WhatsAppMessage.hospital_id == hid, WhatsAppMessage.direction == "outbound",
        WhatsAppMessage.reminder_id.is_not(None),
        msg_time >= start, msg_time < end,
    ).group_by(WhatsAppMessage.status)).all()
    msgs = {s: c for s, c in msg_rows}

    completed_visits = db.execute(select(Appointment.patient_id).where(
        Appointment.hospital_id == hid, Appointment.status == "completed",
        Appointment.start_at >= start, Appointment.start_at < end)).scalars().all()
    patients_seen = set(completed_visits)
    returning = 0
    if patients_seen:
        returning = db.scalar(select(func.count(func.distinct(Appointment.patient_id))).where(
            Appointment.patient_id.in_(patients_seen), Appointment.status == "completed",
            Appointment.start_at < start)) or 0

    names = {p.id: p.full_name for p in db.scalars(select(Patient).where(
        Patient.id.in_([fu.patient_id for fu in fu_completed]))).all()} if fu_completed else {}

    x = len(brought_back_patients)
    return {
        "month": first.strftime("%Y-%m"),
        "month_label": first.strftime("%B %Y"),
        "hospital": hospital.name,
        "summary": f"We brought back {x} patient{'s' if x != 1 else ''} this month.",
        "brought_back": x,
        "includes_simulated_messages": count_simulated,
        "appointments": {
            "total": total_appts,
            "completed": by_status.get("completed", 0),
            "cancelled": by_status.get("cancelled", 0),
            "missed": by_status.get("no_show", 0),
            "rescheduled": by_status.get("rescheduled", 0),
            "still_open": sum(by_status.get(s, 0) for s in ("booked", "confirmed", "reschedule_requested")),
            "confirmed_on_whatsapp": wa_confirmed,
            "completion_rate": _pct(by_status.get("completed", 0), total_appts - by_status.get("cancelled", 0)),
        },
        "follow_ups": {
            "scheduled": fu_created,
            "completed": len(fu_completed),
            "returned_after_reminder": len(brought_back),
            "returned_without_delivered_reminder": len(without_reminder),
            "due_this_month": due_total,
            "due_completed": due_completed,
            "due_missed": due.get("missed", 0),
            "due_open": sum(due.get(s, 0) for s in ("scheduled", "confirmed", "reschedule_requested")),
            "retention_rate": _pct(due_completed, due_total - due_cancelled),
        },
        "patients": {
            "seen": len(patients_seen),
            "returning": returning,
            "new": len(patients_seen) - returning,
        },
        "messages": {
            "accepted": msgs.get("accepted", 0) + msgs.get("sent", 0),
            "delivered": msgs.get("delivered", 0),
            "read": msgs.get("read", 0),
            "failed": msgs.get("failed", 0) + msgs.get("unknown", 0),
            "simulated": msgs.get("simulated", 0),
        },
        "brought_back_list": [
            {"patient": names.get(fu.patient_id, ""), "follow_up_date": fu.due_date.isoformat(),
             "completed_at": fu.completed_at.isoformat() if fu.completed_at else None}
            for fu in brought_back
        ],
    }


def report_csv(report: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["TEC THA Follow-Up Engine — Monthly report"])
    w.writerow(["Hospital", report["hospital"]])
    w.writerow(["Month", report["month_label"]])
    w.writerow(["Summary", report["summary"]])
    if report["includes_simulated_messages"]:
        w.writerow(["Note", "Demo hospital: test-mode (simulated) reminders are counted as delivered."])
    w.writerow([])
    for section in ("appointments", "follow_ups", "patients", "messages"):
        w.writerow([section.replace("_", " ").title()])
        for k, v in report[section].items():
            w.writerow([k.replace("_", " ").capitalize(), "" if v is None else v])
        w.writerow([])
    w.writerow(["Patients brought back"])
    w.writerow(["Patient", "Follow-up date", "Visit recorded at"])
    for row in report["brought_back_list"]:
        w.writerow([row["patient"], row["follow_up_date"], row["completed_at"]])
    return buf.getvalue()
