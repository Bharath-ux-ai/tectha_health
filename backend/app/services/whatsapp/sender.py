"""Turns due reminders into WhatsApp messages.

Modes per hospital:
  disabled – nothing is sent; due reminders are recorded as skipped.
  test     – nothing leaves the server. Messages are stored with status "simulated" and are always
             labelled as such in the UI and reports. Used for demos and onboarding.
  live     – messages are sent through the Cloud API. A message is "accepted" only when Meta returns a
             message id; delivered/read/failed come from status webhooks.
"""
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.clock import hospital_now, local_dt, to_local
from app.core.phone import wa_id
from app.core.security import decrypt_secret
from app.models import (
    Appointment, Doctor, FollowUp, Hospital, MessageEvent, MessageTemplate, Patient, ReminderSchedule, SystemSetting,
    WhatsAppConfig, WhatsAppMessage,
)
from app.services.templates import choose_template, fmt_date, fmt_time, render_named, render_numbered
from app.services.whatsapp.client import AUTH_ERROR_CODES, SendResult, WhatsAppCloudClient

SUCCESS_STATUSES = ("accepted", "sent", "delivered", "read", "simulated")
PAYLOAD_PREFIX = "TT1"


def default_client_factory(cfg: WhatsAppConfig, token: str) -> WhatsAppCloudClient:
    return WhatsAppCloudClient(phone_number_id=cfg.phone_number_id, access_token=token)


# Tests replace this to talk to a mock transport; production always uses the real Graph API client.
client_factory: Callable[[WhatsAppConfig, str], WhatsAppCloudClient] = default_client_factory


def get_config(db: Session, hospital: Hospital) -> WhatsAppConfig:
    cfg = db.get(WhatsAppConfig, hospital.id)
    if cfg is None:
        cfg = WhatsAppConfig(hospital_id=hospital.id, mode="test", test_recipient_allowlist=[])
        db.add(cfg)
        db.flush()
    return cfg


def live_messaging_enabled(db: Session) -> bool:
    row = db.get(SystemSetting, "live_messaging_enabled")
    return True if row is None else bool(row.value.get("enabled", True))


def booking_link(hospital: Hospital) -> str:
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/book/{hospital.slug}"


def _event(db: Session, msg: WhatsAppMessage, event: str, at: datetime, detail: dict | None = None) -> None:
    db.add(MessageEvent(hospital_id=msg.hospital_id, message=msg, event=event, detail=detail, occurred_at=at))


def make_payload(action: str, ref: str) -> str:
    return f"{PAYLOAD_PREFIX}:{action}:{ref}"


def parse_payload(payload: str | None) -> tuple[str, str] | None:
    parts = (payload or "").split(":")
    if len(parts) == 3 and parts[0] == PAYLOAD_PREFIX and parts[1] in ("C", "R") and parts[2]:
        return parts[1], parts[2]
    return None


class LiveGuardError(Exception):
    def __init__(self, reason: str, permanent: bool = True):
        super().__init__(reason)
        self.reason = reason
        self.permanent = permanent


def _live_guard(db: Session, cfg: WhatsAppConfig, patient: Patient) -> str:
    """Checks that must pass before anything is sent to a real phone. Returns the decrypted token."""
    if not live_messaging_enabled(db):
        raise LiveGuardError("live_paused", permanent=False)
    if patient.is_test and patient.phone_e164 not in (cfg.test_recipient_allowlist or []):
        raise LiveGuardError("test_patient_not_allowlisted")
    token = decrypt_secret(cfg.access_token_encrypted)
    if not token or not cfg.phone_number_id:
        raise LiveGuardError("whatsapp_not_configured")
    return token


def reminder_content(db: Session, hospital: Hospital, r: ReminderSchedule, patient: Patient,
                     template: MessageTemplate) -> list[str]:
    lang = template.language
    if r.appointment_id:
        appt = db.get(Appointment, r.appointment_id)
        doctor = db.get(Doctor, appt.doctor_id)
        local = to_local(hospital, appt.start_at)
        return [patient.full_name, hospital.name, doctor.name, fmt_date(local, lang), fmt_time(local)]
    fu = db.get(FollowUp, r.follow_up_id)
    doctor = db.get(Doctor, fu.doctor_id) if fu.doctor_id else None
    return [patient.full_name, hospital.name, doctor.name if doctor else hospital.name, fmt_date(fu.due_date, lang)]


def _skip(r: ReminderSchedule, reason: str, now: datetime) -> str:
    r.status, r.skip_reason, r.processed_at = "skipped", reason, now
    return "skipped"


def _target_still_valid(db: Session, hospital: Hospital, r: ReminderSchedule, now: datetime) -> str | None:
    if r.appointment_id:
        appt = db.get(Appointment, r.appointment_id)
        if appt is None or appt.status not in ("booked", "confirmed"):
            return f"appointment_{appt.status if appt else 'missing'}"
        if appt.start_at <= now:
            return "appointment_passed"
        if to_local(hospital, now).date() >= to_local(hospital, appt.start_at).date():
            return "too_late_for_day_before"  # the text says "tomorrow"; never send it on the day itself
    else:
        fu = db.get(FollowUp, r.follow_up_id)
        if fu is None or fu.status != "scheduled":
            return f"followup_{fu.status if fu else 'missing'}"
        if to_local(hospital, now).date() >= fu.due_date:
            return "followup_date_reached"
        if r.kind == "followup_7d":
            three_day_due = local_dt(hospital, fu.due_date - timedelta(days=3), hospital.followup_reminder_time)
            if now >= three_day_due:
                return "superseded_by_3_day"  # running late: send only the 3-day reminder, not both at once
    return None


def process_reminder(db: Session, hospital: Hospital, r: ReminderSchedule, now: datetime | None = None,
                     *, manual: bool = False) -> str:
    """Send one reminder. Returns the resulting reminder status. Never sends twice for one reminder."""
    now = now or hospital_now(hospital)
    cfg = get_config(db, hospital)
    reason = _target_still_valid(db, hospital, r, now)
    if reason:
        return _skip(r, reason, now)
    patient = db.get(Patient, r.patient_id)
    if patient is None or patient.deleted_at or not patient.whatsapp_opt_in:
        return _skip(r, "no_whatsapp_consent", now)

    # Idempotency: if any attempt for this reminder already succeeded, never send again.
    done = db.scalar(select(WhatsAppMessage).where(
        WhatsAppMessage.reminder_id == r.id, WhatsAppMessage.status.in_(SUCCESS_STATUSES)).limit(1))
    if done:
        r.status = "simulated" if done.is_simulated else "sent"
        r.processed_at = r.processed_at or now
        return r.status
    if cfg.mode == "disabled":
        return _skip(r, "whatsapp_disabled", now)

    kind = "appointment_reminder" if r.appointment_id else "followup_reminder"
    template = choose_template(db, hospital, kind, patient.preferred_language)
    if template is None:
        r.status, r.last_error, r.processed_at = "failed", "No active message template for this reminder.", now
        return "failed"
    params = reminder_content(db, hospital, r, patient, template)
    attempt_no = (db.scalar(select(func.count()).select_from(WhatsAppMessage).where(
        WhatsAppMessage.reminder_id == r.id)) or 0) + 1
    msg = WhatsAppMessage(
        hospital_id=hospital.id, patient_id=patient.id, reminder_id=r.id, direction="outbound",
        message_type="template", template_name=template.meta_template_name, language=template.meta_language_code,
        phone_e164=patient.phone_e164, body_preview=render_numbered(template.body_text, params),
        payload_ref=secrets.token_urlsafe(12), status="queued", attempt_no=attempt_no,
    )
    db.add(msg)

    if cfg.mode == "test":
        msg.status, msg.is_simulated, msg.sent_at = "simulated", True, now
        _event(db, msg, "simulated", now, {"mode": "test", "note": "Test mode: not sent to WhatsApp"})
        r.status, r.processed_at, r.last_error = "simulated", now, None
        return "simulated"

    try:
        token = _live_guard(db, cfg, patient)
    except LiveGuardError as exc:
        db.expunge(msg)
        if not exc.permanent:
            r.status, r.next_attempt_at, r.last_error = "pending", now + timedelta(minutes=30), "Live messaging is paused."
            return "pending"
        return _skip(r, exc.reason, now)
    if template.approval_status != "approved":
        db.expunge(msg)
        r.status, r.processed_at = "failed", now
        r.last_error = f"Template {template.meta_template_name} ({template.language}) is not approved by WhatsApp yet."
        return "failed"

    with client_factory(cfg, token) as client:
        result = client.send_template(
            to=wa_id(patient.phone_e164), template_name=template.meta_template_name,
            language_code=template.meta_language_code or template.language, body_params=params,
            button_payloads=[make_payload("C", msg.payload_ref), make_payload("R", msg.payload_ref)],
        )
    r.attempts += 1
    return _apply_result(db, hospital, cfg, r, msg, result, now, manual=manual)


def _apply_result(db: Session, hospital: Hospital, cfg: WhatsAppConfig, r: ReminderSchedule, msg: WhatsAppMessage,
                  result: SendResult, now: datetime, *, manual: bool) -> str:
    if result.ok:
        msg.status, msg.wa_message_id, msg.sent_at = "accepted", result.wa_message_id, now
        _event(db, msg, "api_accepted", now, {"wamid": result.wa_message_id})
        r.status, r.processed_at, r.last_error, r.next_attempt_at = "sent", now, None, None
        cfg.last_error = None
        return "sent"

    msg.status = "unknown" if result.ambiguous else "failed"
    msg.error_code, msg.error_message, msg.failed_at = result.error_code, result.error_message, now
    _event(db, msg, "api_error", now, {"code": result.error_code, "message": result.error_message,
                                       "http_status": result.http_status, "ambiguous": result.ambiguous})
    if result.error_code and result.error_code.isdigit() and int(result.error_code) in AUTH_ERROR_CODES:
        cfg.last_error = f"WhatsApp rejected the credentials: {result.error_message}"
    backoff = settings.retry_backoff_minutes
    if result.retryable and not result.ambiguous and not manual and r.attempts < settings.REMINDER_MAX_ATTEMPTS:
        delay = backoff[min(r.attempts - 1, len(backoff) - 1)]
        r.status, r.next_attempt_at = "pending", now + timedelta(minutes=delay)
        r.last_error = f"Attempt {r.attempts} failed ({result.error_code}). Retrying at {to_local(hospital, r.next_attempt_at):%H:%M}."
        return "pending"
    r.status, r.processed_at = "failed", now
    if result.ambiguous:
        r.last_error = ("WhatsApp did not answer in time, so we can't tell whether the message went out. "
                        "Not retried automatically to avoid a duplicate. Check with the patient before retrying.")
    else:
        r.last_error = f"{result.error_code}: {result.error_message}"
    return "failed"


def retry_failed_reminder(db: Session, hospital: Hospital, r: ReminderSchedule) -> str:
    """Staff-initiated retry. Refuses if the reminder already succeeded or the target is no longer valid."""
    if r.status != "failed":
        from app.core.errors import ServiceError
        raise ServiceError("Only failed reminders can be retried.")
    r.status = "processing"
    r.claimed_at = hospital_now(hospital)
    return process_reminder(db, hospital, r, manual=True)


def send_session_text(db: Session, hospital: Hospital, patient: Patient, text: str, *,
                      reply_to: WhatsAppMessage | None, now: datetime) -> WhatsAppMessage | None:
    """Free-form reply inside the 24h customer-service window opened by the patient's button tap."""
    cfg = get_config(db, hospital)
    if cfg.mode == "disabled":
        return None
    msg = WhatsAppMessage(hospital_id=hospital.id, patient_id=patient.id, direction="outbound", message_type="text",
                          phone_e164=patient.phone_e164, body_preview=text, status="queued",
                          reply_to_message_id=reply_to.id if reply_to else None)
    db.add(msg)
    if cfg.mode == "test":
        msg.status, msg.is_simulated, msg.sent_at = "simulated", True, now
        _event(db, msg, "simulated", now, {"mode": "test"})
        return msg
    try:
        token = _live_guard(db, cfg, patient)
    except LiveGuardError as exc:
        msg.status, msg.error_code, msg.error_message, msg.failed_at = "failed", "guard", exc.reason, now
        return msg
    with client_factory(cfg, token) as client:
        result = client.send_text(to=wa_id(patient.phone_e164), text=text)
    if result.ok:
        msg.status, msg.wa_message_id, msg.sent_at = "accepted", result.wa_message_id, now
        _event(db, msg, "api_accepted", now, {"wamid": result.wa_message_id})
    else:
        msg.status = "unknown" if result.ambiguous else "failed"
        msg.error_code, msg.error_message, msg.failed_at = result.error_code, result.error_message, now
        _event(db, msg, "api_error", now, {"code": result.error_code, "message": result.error_message})
    return msg


def reply_text(db: Session, hospital: Hospital, patient: Patient, kind: str, when: str = "") -> str:
    tpl = choose_template(db, hospital, kind, patient.preferred_language)
    body = tpl.body_text if tpl else "{hospital}"
    return render_named(body, {"name": patient.full_name, "when": when, "hospital": hospital.name,
                               "booking_link": booking_link(hospital), "hospital_phone": hospital.phone or ""})
