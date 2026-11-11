"""Demo environment for hospital-owner presentations (fictional data only).

Scenario from the Version 1 brief: Mr. Ravi books on Monday, gets a WhatsApp reminder on Tuesday evening,
taps Confirm, visits on Wednesday, gets a follow-up two weeks later (2 December for a 16 November start),
receives reminders 7 and 3 days before, and turns red on the dashboard if he does not respond.

The demo hospital runs on its own adjustable clock (an offset from real time); real hospitals never do.
Every patient in a demo hospital is flagged is_test, so live mode can only message allowlisted phones.
"""
import math
import secrets
import uuid
from datetime import date, datetime, time, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core.clock import hospital_now, local_dt, to_local, utcnow
from app.core.errors import NotFound, ServiceError
from app.models import (
    Appointment, ContactLog, Doctor, DoctorAvailability, FollowUp, Hospital, MonthlyReport, Patient, PatientConsent,
    ReminderSchedule, SystemSetting, WebhookEvent, WhatsAppMessage,
)
from app.services import booking, engine, followups, patients
from app.services.whatsapp.sender import get_config
from app.services.whatsapp.webhook import apply_patient_action

DEFAULT_START_MONDAY = date(2026, 11, 16)
DEMO_SLUG = "tectha-demo-clinic"

BACKGROUND_PATIENTS = [
    ("Lakshmi Narayanan", "+919000000101", "ta"), ("Karthik Raman", "+919000000102", "en"),
    ("Priya Selvam", "+919000000103", "ta"), ("Senthil Kumar", "+919000000104", "ta"),
    ("Anitha Rajendran", "+919000000105", "en"), ("Murugan Pandian", "+919000000106", "ta"),
    ("Fathima Begum", "+919000000107", "en"), ("Joseph Devaraj", "+919000000108", "en"),
]


def _settings_key(hospital: Hospital) -> str:
    return f"demo:{hospital.id}"


def get_start_monday(db: Session, hospital: Hospital) -> date:
    row = db.get(SystemSetting, _settings_key(hospital))
    if row and row.value.get("start_monday"):
        return date.fromisoformat(row.value["start_monday"])
    return DEFAULT_START_MONDAY


def _save(db: Session, hospital: Hospital, **values) -> None:
    row = db.get(SystemSetting, _settings_key(hospital))
    if row is None:
        db.add(SystemSetting(key=_settings_key(hospital), value=dict(values)))
    else:
        row.value = {**row.value, **values}


def require_demo(hospital: Hospital) -> None:
    if not hospital.is_demo:
        raise ServiceError("Demo controls are only available for demo hospitals.", 403)


def set_clock(db: Session, hospital: Hospital, local_when: datetime) -> datetime:
    require_demo(hospital)
    target = local_when if local_when.tzinfo else local_when.replace(tzinfo=to_local(hospital, utcnow()).tzinfo)
    # ceil, so the demo clock never lands a fraction of a second *before* the requested moment
    hospital.demo_clock_offset_seconds = math.ceil((target - utcnow()).total_seconds())
    return hospital_now(hospital)


def scenario(start: date) -> dict:
    follow_up = start + timedelta(days=16)  # Wednesday two weeks after the first visit
    return {
        "book": start, "reminder": start + timedelta(days=1), "visit": start + timedelta(days=2),
        "follow_up": follow_up, "reminder_7d": follow_up - timedelta(days=7),
        "reminder_3d": follow_up - timedelta(days=3), "red": follow_up - timedelta(days=2),
    }


def steps(db: Session, hospital: Hospital) -> list[dict]:
    s = scenario(get_start_monday(db, hospital))
    appt_t, fu_t = hospital.appointment_reminder_time, hospital.followup_reminder_time
    plus5 = lambda t: (datetime.combine(date.today(), t) + timedelta(minutes=5)).time()  # noqa: E731
    return [
        {"key": "book", "at": local_dt(hospital, s["book"], time(10, 0)), "run_engine": False,
         "title": "Mr. Ravi books online", "detail": "Open the booking page and book a slot for Wednesday as Ravi."},
        {"key": "reminder", "at": local_dt(hospital, s["reminder"], plus5(appt_t)), "run_engine": True,
         "title": "Day-before reminder goes out", "detail": "Tuesday evening: the reminder engine sends the WhatsApp reminder."},
        {"key": "confirm", "at": None, "run_engine": False,
         "title": "Ravi taps Confirm", "detail": "Simulates his tap in test mode. In live mode, tap Confirm on the phone."},
        {"key": "visit", "at": local_dt(hospital, s["visit"], time(10, 45)), "run_engine": False,
         "title": "Visit done, follow-up set", "detail": f"Staff marks the visit completed and sets the follow-up for {s['follow_up']:%d %b}."},
        {"key": "reminder_7d", "at": local_dt(hospital, s["reminder_7d"], plus5(fu_t)), "run_engine": True,
         "title": "7-day follow-up reminder", "detail": f"{s['reminder_7d']:%d %b}: first follow-up reminder."},
        {"key": "reminder_3d", "at": local_dt(hospital, s["reminder_3d"], plus5(fu_t)), "run_engine": True,
         "title": "3-day follow-up reminder", "detail": f"{s['reminder_3d']:%d %b}: second follow-up reminder."},
        {"key": "red", "at": local_dt(hospital, s["red"], time(9, 0)), "run_engine": True,
         "title": "No reply — Ravi turns red", "detail": "Two days before the visit with no reply, the dashboard flags him for a call."},
    ]


def find_ravi(db: Session, hospital: Hospital) -> Patient | None:
    return db.scalar(select(Patient).where(Patient.hospital_id == hospital.id, Patient.name_normalized.like("%ravi%"),
                                           Patient.deleted_at.is_(None)).order_by(Patient.created_at.desc()).limit(1))


def run_step(db: Session, hospital: Hospital, key: str, *, user_id: uuid.UUID | None = None) -> dict:
    require_demo(hospital)
    step = next((s for s in steps(db, hospital) if s["key"] == key), None)
    if step is None:
        raise NotFound("Unknown demo step.")
    result: dict = {"step": key}
    if step["at"]:
        set_clock(db, hospital, step["at"])
        db.commit()
    if key == "confirm":
        ravi = find_ravi(db, hospital)
        msg = ravi and db.scalar(select(WhatsAppMessage).join(ReminderSchedule, ReminderSchedule.id == WhatsAppMessage.reminder_id)
                                 .where(WhatsAppMessage.patient_id == ravi.id, ReminderSchedule.kind == "appointment_day_before",
                                        WhatsAppMessage.direction == "outbound")
                                 .order_by(WhatsAppMessage.created_at.desc()).limit(1))
        if not msg:
            raise ServiceError("No reminder has been sent to Ravi yet. Book as Ravi, then run the reminder step.")
        result["outcome"] = simulate_reply(db, hospital, msg.id, "C")
    if key == "visit":
        result.update(complete_ravi_visit(db, hospital, user_id=user_id))
    if step["run_engine"]:
        result["engine"] = engine.run_hospital(db, hospital)
    db.commit()
    return result


def complete_ravi_visit(db: Session, hospital: Hospital, *, user_id: uuid.UUID | None) -> dict:
    ravi = find_ravi(db, hospital)
    if ravi is None:
        raise ServiceError("Book an appointment as Ravi first.")
    s = scenario(get_start_monday(db, hospital))
    appt = db.scalar(select(Appointment).where(Appointment.patient_id == ravi.id,
                                               Appointment.status.in_(("booked", "confirmed", "completed")))
                     .order_by(Appointment.start_at).limit(1))
    if appt is None:
        raise ServiceError("Ravi has no appointment to complete.")
    if appt.status != "completed":
        booking.change_status(db, hospital, appt, "completed")
    fu = db.scalar(select(FollowUp).where(FollowUp.source_appointment_id == appt.id))
    if fu is None:
        fu = followups.create_followup(db, hospital, patient=ravi, due_date=s["follow_up"], source_appointment=appt,
                                       doctor_id=appt.doctor_id, note=None, user_id=user_id)
    return {"appointment_id": str(appt.id), "follow_up_id": str(fu.id), "follow_up_date": fu.due_date.isoformat()}


def simulate_reply(db: Session, hospital: Hospital, message_id: uuid.UUID, action: str) -> str:
    """Runs the same rules as a real webhook tap, for messages sent in test mode."""
    require_demo(hospital)
    msg = db.get(WhatsAppMessage, message_id)
    if not msg or msg.hospital_id != hospital.id or msg.direction != "outbound" or not msg.reminder_id:
        raise NotFound("Reminder message not found.")
    if action not in ("C", "R"):
        raise ServiceError("Action must be Confirm or Reschedule.")
    now = hospital_now(hospital)
    db.add(WhatsAppMessage(
        hospital_id=hospital.id, patient_id=msg.patient_id, direction="inbound", message_type="button",
        phone_e164=msg.phone_e164, body_preview=("Confirm" if action == "C" else "Reschedule") + " (simulated tap)",
        status="received", is_simulated=True, reply_to_message_id=msg.id, sent_at=now,
        payload_ref=None, wa_message_id=f"sim-{secrets.token_hex(8)}",
    ))
    r = db.get(ReminderSchedule, msg.reminder_id)
    return apply_patient_action(db, hospital, r, action, reply_to=msg, now=now)


def wipe(db: Session, hospital: Hospital) -> None:
    hid = hospital.id
    db.execute(update(WhatsAppMessage).where(WhatsAppMessage.hospital_id == hid).values(reply_to_message_id=None))
    db.execute(delete(WhatsAppMessage).where(WhatsAppMessage.hospital_id == hid))
    db.execute(delete(WebhookEvent).where(WebhookEvent.hospital_id == hid))
    db.execute(delete(ReminderSchedule).where(ReminderSchedule.hospital_id == hid))
    db.execute(delete(ContactLog).where(ContactLog.hospital_id == hid))
    db.execute(update(Appointment).where(Appointment.hospital_id == hid).values(follow_up_id=None, rescheduled_to_id=None))
    db.execute(delete(FollowUp).where(FollowUp.hospital_id == hid))
    db.execute(delete(Appointment).where(Appointment.hospital_id == hid))
    db.execute(delete(PatientConsent).where(PatientConsent.hospital_id == hid))
    db.execute(delete(Patient).where(Patient.hospital_id == hid))
    db.execute(delete(MonthlyReport).where(MonthlyReport.hospital_id == hid))


def ensure_doctors(db: Session, hospital: Hospital) -> list[Doctor]:
    docs = db.scalars(select(Doctor).where(Doctor.hospital_id == hospital.id, Doctor.deleted_at.is_(None))).all()
    if docs:
        return list(docs)
    out = []
    for name, specialty in (("Dr. Meena Sundaram", "General Medicine"), ("Dr. Arjun Prakash", "Cardiology")):
        doc = Doctor(hospital_id=hospital.id, name=name, specialty=specialty)
        db.add(doc)
        db.flush()
        for wd in range(6):  # Monday–Saturday
            for start, end in ((time(9, 0), time(13, 0)), (time(16, 0), time(19, 0))):
                db.add(DoctorAvailability(hospital_id=hospital.id, doctor_id=doc.id, weekday=wd,
                                          start_time=start, end_time=end, slot_minutes=15))
        out.append(doc)
    db.flush()
    return out


def reset(db: Session, hospital: Hospital, start_monday: date | None = None) -> dict:
    require_demo(hospital)
    start = start_monday or get_start_monday(db, hospital)
    if start.weekday() != 0:
        raise ServiceError("The demo week must start on a Monday.")
    _save(db, hospital, start_monday=start.isoformat())
    wipe(db, hospital)
    docs = ensure_doctors(db, hospital)
    cfg = get_config(db, hospital)
    if cfg.mode == "live" and not cfg.test_recipient_allowlist:
        cfg.mode = "test"
    people = {}
    for name, phone, lang in BACKGROUND_PATIENTS:
        people[name] = patients.find_or_create_patient(
            db, hospital, full_name=name, phone=phone, language=lang, is_test=True,
            whatsapp_consent=name != "Murugan Pandian", consent_source="staff_verbal")
    meena, arjun = docs[0], docs[-1]
    db.commit()

    _play_history(db, hospital, start, people, meena)

    # The demo week itself
    set_clock(db, hospital, local_dt(hospital, start, time(9, 30)))
    db.flush()
    plan = [
        ("Lakshmi Narayanan", meena, 0, time(11, 0), "confirmed"), ("Karthik Raman", arjun, 0, time(11, 30), "booked"),
        ("Priya Selvam", meena, 0, time(16, 0), "booked"), ("Murugan Pandian", arjun, 1, time(10, 0), "booked"),
        ("Anitha Rajendran", meena, 1, time(12, 0), "booked"), ("Joseph Devaraj", arjun, 2, time(9, 30), "booked"),
        ("Karthik Raman", meena, 2, time(17, 0), "booked"),
        # Bookings on the later scenario days, so the dashboard is not empty when Ravi turns red
        ("Priya Selvam", meena, 9, time(10, 0), "booked"), ("Lakshmi Narayanan", arjun, 14, time(9, 15), "booked"),
        ("Joseph Devaraj", meena, 14, time(11, 0), "booked"), ("Anitha Rajendran", meena, 14, time(16, 30), "booked"),
    ]
    for name, doc, offset, t, status in plan:
        try:
            appt = booking.book_appointment(db, hospital, patient=people[name], doctor=doc,
                                            start_at=local_dt(hospital, start + timedelta(days=offset), t), source="staff")
        except ServiceError:
            continue
        if status == "confirmed":
            booking.change_status(db, hospital, appt, "confirmed")
    followups.create_followup(db, hospital, patient=people["Senthil Kumar"], due_date=start + timedelta(days=5),
                              source_appointment=None, doctor_id=meena.id, note=None, user_id=None)
    db.commit()
    return {"start_monday": start.isoformat(), "clock": hospital_now(hospital).isoformat()}


def _play_history(db: Session, hospital: Hospital, start: date, people: dict, doctor: Doctor) -> None:
    """Plays the two weeks before the demo week through the real engine, so the monthly report has
    genuine numbers: three patients come back after reminders, one comes back without a reminder
    (no WhatsApp consent, so he is not credited to the reminders) and one misses her follow-up."""
    t0 = start - timedelta(days=14)
    set_clock(db, hospital, local_dt(hospital, t0, time(9, 0)))
    plan = {"Lakshmi Narayanan": -6, "Karthik Raman": -5, "Priya Selvam": -4, "Murugan Pandian": -3,
            "Fathima Begum": -2}
    fus = {}
    for name, offset in plan.items():
        fus[name] = followups.create_followup(db, hospital, patient=people[name], due_date=start + timedelta(days=offset),
                                              source_appointment=None, doctor_id=doctor.id, note=None, user_id=None)
    db.commit()
    visit_times = iter([time(10, 0), time(10, 15), time(10, 30), time(10, 45), time(11, 0)])
    for i in range(1, 14):
        day = t0 + timedelta(days=i)
        set_clock(db, hospital, local_dt(hospital, day, (datetime.combine(day, hospital.followup_reminder_time)
                                                         + timedelta(minutes=5)).time()))
        engine.run_hospital(db, hospital)
        for name, fu in fus.items():
            if fu.due_date == day and name != "Fathima Begum":
                set_clock(db, hospital, local_dt(hospital, day, time(9, 45)))
                appt = booking.book_appointment(db, hospital, patient=people[name], doctor=doctor,
                                                start_at=local_dt(hospital, day, next(visit_times)), source="staff",
                                                lead_minutes=0)
                set_clock(db, hospital, local_dt(hospital, day, time(12, 0)))
                booking.change_status(db, hospital, appt, "completed")
        db.commit()
    set_clock(db, hospital, local_dt(hospital, start - timedelta(days=1), time(20, 0)))
    engine.run_hospital(db, hospital)  # marks Fathima's follow-up as missed
    db.commit()


def state(db: Session, hospital: Hospital) -> dict:
    require_demo(hospital)
    cfg = get_config(db, hospital)
    start = get_start_monday(db, hospital)
    now = hospital_now(hospital)
    ravi = find_ravi(db, hospital)
    msgs = []
    if ravi:
        for m in db.scalars(select(WhatsAppMessage).where(WhatsAppMessage.patient_id == ravi.id)
                            .order_by(WhatsAppMessage.created_at)).all():
            msgs.append({"id": str(m.id), "direction": m.direction, "status": m.status, "body": m.body_preview,
                         "is_simulated": m.is_simulated, "at": (m.sent_at or m.created_at).isoformat(),
                         "has_buttons": bool(m.reminder_id and m.direction == "outbound")})
    return {
        "now": now.isoformat(), "local_now": to_local(hospital, now).strftime("%a %d %b %Y, %I:%M %p"),
        "start_monday": start.isoformat(),
        "scenario": {k: v.isoformat() for k, v in scenario(start).items()},
        "steps": [{**s, "at": s["at"].isoformat() if s["at"] else None} for s in steps(db, hospital)],
        "whatsapp_mode": cfg.mode, "allowlist": cfg.test_recipient_allowlist or [],
        "ravi": {"id": str(ravi.id), "name": ravi.full_name, "phone": ravi.phone_e164} if ravi else None,
        "ravi_messages": msgs,
    }
