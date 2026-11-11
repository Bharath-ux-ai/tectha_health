"""Incoming WhatsApp webhooks: delivery statuses and patient button replies (Confirm / Reschedule)."""
import hashlib
import hmac
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.core.clock import hospital_now, to_local
from app.models import (
    Appointment, FollowUp, Hospital, Patient, ReminderSchedule, WebhookEvent, WhatsAppConfig, WhatsAppMessage,
)
from app.services import booking, followups, patients
from app.services.templates import fmt_date, fmt_time
from app.services.whatsapp.sender import _event, parse_payload, reply_text, send_session_text

log = logging.getLogger("tectha.webhook")

STATUS_RANK = {"queued": 0, "accepted": 1, "sent": 2, "delivered": 3, "read": 4}
STOP_WORDS = {"STOP", "UNSUBSCRIBE", "STOP ALL", "நிறுத்து", "நிறுத்தவும்"}


def verify_signature(raw_body: bytes, header: str | None) -> bool:
    if not settings.WHATSAPP_APP_SECRET:
        return settings.ALLOW_UNSIGNED_WEBHOOKS and not settings.is_production
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(settings.WHATSAPP_APP_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[7:])


def _record(db: Session, key: str, payload: dict, hospital_id) -> WebhookEvent | None:
    """Store the item once. Returns None when Meta redelivers something we already processed."""
    ev = WebhookEvent(dedupe_key=key[:240], payload=payload, hospital_id=hospital_id)
    try:
        with db.begin_nested():
            db.add(ev)
            db.flush()
    except IntegrityError:
        return None
    return ev


def _ts(hospital: Hospital, raw: str | None) -> datetime:
    if hospital.is_demo or not raw:
        return hospital_now(hospital)
    try:
        return datetime.fromtimestamp(int(raw), tz=timezone.utc)
    except (TypeError, ValueError):
        return hospital_now(hospital)


def process_payload(db: Session, payload: dict) -> dict:
    stats = {"statuses": 0, "messages": 0, "duplicates": 0, "ignored": 0}
    if payload.get("object") != "whatsapp_business_account":
        stats["ignored"] += 1
        return stats
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            if change.get("field") != "messages":
                continue
            value = change.get("value") or {}
            pnid = (value.get("metadata") or {}).get("phone_number_id")
            cfg = db.scalar(select(WhatsAppConfig).where(WhatsAppConfig.phone_number_id == pnid)) if pnid else None
            if cfg is None:
                stats["ignored"] += 1
                log.warning("Webhook for unknown phone_number_id %s", pnid)
                continue
            hospital = db.get(Hospital, cfg.hospital_id)
            for st in value.get("statuses") or []:
                ev = _record(db, f"status:{st.get('id')}:{st.get('status')}", st, hospital.id)
                if ev is None:
                    stats["duplicates"] += 1
                    continue
                ev.outcome = handle_status(db, hospital, st)
                stats["statuses"] += 1
            for m in value.get("messages") or []:
                ev = _record(db, f"msg:{m.get('id')}", m, hospital.id)
                if ev is None:
                    stats["duplicates"] += 1
                    continue
                ev.outcome = handle_inbound(db, hospital, m)
                stats["messages"] += 1
    return stats


def handle_status(db: Session, hospital: Hospital, st: dict) -> str:
    msg = db.scalar(select(WhatsAppMessage).where(WhatsAppMessage.wa_message_id == st.get("id"),
                                                  WhatsAppMessage.hospital_id == hospital.id))
    if msg is None:
        return "unknown_message"
    status = st.get("status")
    at = _ts(hospital, st.get("timestamp"))
    errors = st.get("errors") or []
    _event(db, msg, status or "unknown", at, {"errors": errors} if errors else None)
    if status in ("sent", "delivered", "read"):
        if msg.status == "failed" or STATUS_RANK.get(status, 0) > STATUS_RANK.get(msg.status, 0):
            msg.status = status
        if status == "delivered":
            msg.delivered_at = msg.delivered_at or at
        if status == "read":
            msg.read_at = msg.read_at or at
            msg.delivered_at = msg.delivered_at or at
        return f"status_{status}"
    if status == "failed":
        if msg.status not in ("delivered", "read"):
            msg.status, msg.failed_at = "failed", at
            if errors:
                msg.error_code = str(errors[0].get("code"))
                msg.error_message = errors[0].get("title") or errors[0].get("message")
            if msg.reminder_id:
                r = db.get(ReminderSchedule, msg.reminder_id)
                other_ok = db.scalar(select(WhatsAppMessage.id).where(
                    WhatsAppMessage.reminder_id == r.id, WhatsAppMessage.id != msg.id,
                    WhatsAppMessage.status.in_(("accepted", "sent", "delivered", "read"))).limit(1))
                if r and not other_ok:
                    r.status = "failed"
                    r.last_error = f"WhatsApp could not deliver: {msg.error_code} {msg.error_message or ''}".strip()
        return "status_failed"
    return "status_ignored"


def handle_inbound(db: Session, hospital: Hospital, m: dict) -> str:
    phone = "+" + str(m.get("from", "")).lstrip("+")
    mtype = m.get("type")
    payload, label, text_body = None, None, None
    if mtype == "button":
        payload, label = (m.get("button") or {}).get("payload"), (m.get("button") or {}).get("text")
    elif mtype == "interactive":
        reply = (m.get("interactive") or {}).get("button_reply") or {}
        payload, label = reply.get("id"), reply.get("title")
    elif mtype == "text":
        text_body = (m.get("text") or {}).get("body", "")
    at = _ts(hospital, m.get("timestamp"))

    patient_rows = db.scalars(select(Patient).where(Patient.hospital_id == hospital.id, Patient.phone_e164 == phone,
                                                    Patient.deleted_at.is_(None))).all()
    parsed = parse_payload(payload)
    original = None
    if parsed:
        original = db.scalar(select(WhatsAppMessage).where(WhatsAppMessage.payload_ref == parsed[1],
                                                           WhatsAppMessage.hospital_id == hospital.id))
    patient = (db.get(Patient, original.patient_id) if original and original.patient_id else
               (patient_rows[0] if len(patient_rows) == 1 else None))
    inbound = WhatsAppMessage(
        hospital_id=hospital.id, patient_id=patient.id if patient else None, direction="inbound",
        message_type="button" if parsed or payload else (mtype or "unknown")[:16], phone_e164=phone,
        body_preview=label or text_body or f"[{mtype}]", wa_message_id=m.get("id"), status="received",
        reply_to_message_id=original.id if original else None, sent_at=at,
    )
    db.add(inbound)

    if text_body is not None and text_body.strip().upper() in STOP_WORDS:
        for p in patient_rows:
            patients.set_consent(db, p, False, source="whatsapp_stop")
        return "opt_out"
    if not parsed:
        return "stored"
    if original is None:
        return "unknown_payload"
    if original.phone_e164 != phone:
        # The reply must come from the number we messaged; anything else is ignored.
        return "phone_mismatch"
    action = parsed[0]
    r = db.get(ReminderSchedule, original.reminder_id) if original.reminder_id else None
    if r is None:
        return "no_reminder"
    return apply_patient_action(db, hospital, r, action, reply_to=original, now=at)


def apply_patient_action(db: Session, hospital: Hospital, r: ReminderSchedule, action: str, *,
                         reply_to: WhatsAppMessage | None, now: datetime) -> str:
    """Shared by the real webhook and the demo 'simulate reply' control, so both follow the same rules."""
    patient = db.get(Patient, r.patient_id)
    if r.appointment_id:
        appt = db.get(Appointment, r.appointment_id)
        when = f"{fmt_date(to_local(hospital, appt.start_at), patient.preferred_language)}, {fmt_time(to_local(hospital, appt.start_at))}"
        if action == "C":
            if appt.status in ("booked", "reschedule_requested"):
                booking.change_status(db, hospital, appt, "confirmed", via="whatsapp")
            elif appt.status != "confirmed":
                send_session_text(db, hospital, patient, reply_text(db, hospital, patient, "reschedule_reply"),
                                  reply_to=reply_to, now=now)
                return f"appointment_not_active_{appt.status}"
            send_session_text(db, hospital, patient, reply_text(db, hospital, patient, "confirm_reply", when),
                              reply_to=reply_to, now=now)
            return "appointment_confirmed"
        if appt.status in ("booked", "confirmed"):
            booking.change_status(db, hospital, appt, "reschedule_requested", via="whatsapp")
        send_session_text(db, hospital, patient, reply_text(db, hospital, patient, "reschedule_reply"),
                          reply_to=reply_to, now=now)
        return "appointment_reschedule_requested"

    fu = db.get(FollowUp, r.follow_up_id)
    if fu.status in ("completed", "cancelled"):
        return f"followup_closed_{fu.status}"
    if action == "C" and to_local(hospital, now).date() > fu.due_date:
        action = "R"  # the date has passed; a late "Confirm" becomes a request for a new date
    if action == "C":
        if fu.status in ("scheduled", "reschedule_requested"):
            fu.status, fu.confirmed_at = "confirmed", now
            from app.services import reminders
            reminders.cancel_pending(db, follow_up_id=fu.id)
        appt = followups.autobook_followup(db, hospital, fu)
        lang = patient.preferred_language
        when = (f"{fmt_date(to_local(hospital, appt.start_at), lang)}, {fmt_time(to_local(hospital, appt.start_at))}"
                if appt else fmt_date(fu.due_date, lang))
        send_session_text(db, hospital, patient, reply_text(db, hospital, patient, "confirm_reply", when),
                          reply_to=reply_to, now=now)
        return "followup_confirmed_booked" if appt else "followup_confirmed_needs_time"
    fu.status, fu.reschedule_requested_at = "reschedule_requested", now
    from app.services import reminders
    reminders.cancel_pending(db, follow_up_id=fu.id)
    if fu.booked_appointment_id:
        booked = db.get(Appointment, fu.booked_appointment_id)
        if booked and booked.status in ("booked", "confirmed"):
            booking.change_status(db, hospital, booked, "reschedule_requested", via="whatsapp")
    send_session_text(db, hospital, patient, reply_text(db, hospital, patient, "reschedule_reply"),
                      reply_to=reply_to, now=now)
    return "followup_reschedule_requested"
