"""WhatsApp configuration, message templates, message log and reminder queue."""
import uuid

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.appointments import reminder_out
from app.api.common import iso, message_out
from app.config import settings
from app.core.clock import hospital_now, utcnow
from app.core.deps import CurrentUser, client_ip, get_owned, require_hospital
from app.core.errors import ServiceError
from app.core.phone import InvalidPhone, normalize_phone
from app.core.security import decrypt_secret, encrypt_secret
from app.db import get_db
from app.models import Hospital, MessageTemplate, Patient, ReminderSchedule, WhatsAppConfig, WhatsAppMessage
from app.services.audit import audit
from app.services.templates import (
    EXAMPLE_PARAMS, REPLY_PLACEHOLDERS, TEMPLATE_PARAMS, example_params, render_named, render_numbered, validate_template_body,
)
from app.services.whatsapp import sender
from app.services.whatsapp.client import template_definition

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])


def _config_out(db: Session, h: Hospital, cfg: WhatsAppConfig) -> dict:
    token = decrypt_secret(cfg.access_token_encrypted)
    return {
        "mode": cfg.mode, "phone_number_id": cfg.phone_number_id, "business_account_id": cfg.business_account_id,
        "display_phone_number": cfg.display_phone_number, "token_set": bool(token),
        "token_last4": token[-4:] if token else None, "test_recipient_allowlist": cfg.test_recipient_allowlist or [],
        "last_verified_at": iso(cfg.last_verified_at), "last_error": cfg.last_error,
        "webhook_url": f"{settings.PUBLIC_BASE_URL.rstrip('/')}/api/webhooks/whatsapp",
        "platform": {"app_secret_set": bool(settings.WHATSAPP_APP_SECRET),
                     "verify_token_set": bool(settings.WHATSAPP_VERIFY_TOKEN),
                     "graph_version": settings.WHATSAPP_GRAPH_VERSION,
                     "live_messaging_enabled": sender.live_messaging_enabled(db)},
        "is_demo": h.is_demo,
        "readiness": _readiness(db, h, cfg, bool(token)),
    }


def _readiness(db: Session, h: Hospital, cfg: WhatsAppConfig, token_set: bool) -> list[dict]:
    approved = db.scalar(select(func.count()).select_from(MessageTemplate).where(
        MessageTemplate.hospital_id == h.id, MessageTemplate.requires_approval.is_(True),
        MessageTemplate.is_active.is_(True), MessageTemplate.approval_status == "approved")) or 0
    needed = db.scalar(select(func.count()).select_from(MessageTemplate).where(
        MessageTemplate.hospital_id == h.id, MessageTemplate.requires_approval.is_(True),
        MessageTemplate.is_active.is_(True))) or 0
    return [
        {"key": "credentials", "ok": bool(cfg.phone_number_id and cfg.business_account_id and token_set),
         "label": "Phone number ID, business account ID and access token saved"},
        {"key": "verified", "ok": cfg.last_verified_at is not None and not cfg.last_error,
         "label": "Credentials verified with WhatsApp"},
        {"key": "webhook", "ok": bool(settings.WHATSAPP_APP_SECRET and settings.WHATSAPP_VERIFY_TOKEN),
         "label": "Webhook secret and verify token configured on the server"},
        {"key": "templates", "ok": needed > 0 and approved == needed,
         "label": f"Reminder templates approved by WhatsApp ({approved} of {needed})"},
    ]


@router.get("/config")
def get_config(current: CurrentUser = Depends(require_hospital("whatsapp:manage")), db: Session = Depends(get_db)):
    h = db.get(Hospital, current.hospital_id)
    cfg = sender.get_config(db, h)
    db.commit()
    return _config_out(db, h, cfg)


class ConfigIn(BaseModel):
    mode: str | None = Field(default=None, pattern="^(disabled|test|live)$")
    phone_number_id: str | None = Field(default=None, max_length=40, pattern=r"^\d*$")
    business_account_id: str | None = Field(default=None, max_length=40, pattern=r"^\d*$")
    access_token: str | None = Field(default=None, max_length=1000)  # write-only
    test_recipient_allowlist: list[str] | None = Field(default=None, max_length=20)


@router.put("/config")
def update_config(body: ConfigIn, request: Request, current: CurrentUser = Depends(require_hospital("whatsapp:manage")),
                  db: Session = Depends(get_db)):
    h = db.get(Hospital, current.hospital_id)
    cfg = sender.get_config(db, h)
    changed = []
    if body.phone_number_id is not None and body.phone_number_id != (cfg.phone_number_id or ""):
        clash = db.scalar(select(WhatsAppConfig.hospital_id).where(
            WhatsAppConfig.phone_number_id == body.phone_number_id, WhatsAppConfig.hospital_id != h.id))
        if clash:
            raise ServiceError("This WhatsApp phone number is already connected to another hospital.", 409)
        cfg.phone_number_id = body.phone_number_id or None
        cfg.last_verified_at = None
        changed.append("phone_number_id")
    if body.business_account_id is not None:
        cfg.business_account_id = body.business_account_id or None
        changed.append("business_account_id")
    if body.access_token:
        cfg.access_token_encrypted = encrypt_secret(body.access_token.strip())
        cfg.last_verified_at, cfg.last_error = None, None
        changed.append("access_token")
    if body.test_recipient_allowlist is not None:
        try:
            cfg.test_recipient_allowlist = sorted({normalize_phone(p) for p in body.test_recipient_allowlist if p.strip()})
        except InvalidPhone as exc:
            raise ServiceError(f"Test phone list: {exc}") from exc
        changed.append("test_recipient_allowlist")
    if body.mode is not None and body.mode != cfg.mode:
        if body.mode == "live":
            token = decrypt_secret(cfg.access_token_encrypted)
            if not (cfg.phone_number_id and token):
                raise ServiceError("Save the phone number ID and access token before switching to live.")
            if h.is_demo and not cfg.test_recipient_allowlist:
                raise ServiceError("Add the phone that will receive demo messages before switching the demo to live.")
        cfg.mode = body.mode
        changed.append(f"mode={body.mode}")
    audit(db, "whatsapp.config_updated", hospital_id=h.id, user_id=current.id, details={"changed": changed},
          ip=client_ip(request))
    db.commit()
    return _config_out(db, h, cfg)


@router.post("/config/verify")
def verify(request: Request, current: CurrentUser = Depends(require_hospital("whatsapp:manage")),
           db: Session = Depends(get_db)):
    """Calls the Graph API with the saved credentials and records the result."""
    h = db.get(Hospital, current.hospital_id)
    cfg = sender.get_config(db, h)
    token = decrypt_secret(cfg.access_token_encrypted)
    if not (cfg.phone_number_id and token):
        raise ServiceError("Save the phone number ID and access token first.")
    with sender.client_factory(cfg, token) as client:
        ok, data = client.get_phone_number()
    if ok:
        cfg.display_phone_number = data.get("display_phone_number")
        cfg.last_verified_at, cfg.last_error = utcnow(), None
    else:
        cfg.last_error = (data.get("error") or {}).get("message", "Verification failed.")
    audit(db, "whatsapp.verified", hospital_id=h.id, user_id=current.id, details={"ok": ok}, ip=client_ip(request))
    db.commit()
    return {"ok": ok, "details": {k: data.get(k) for k in ("display_phone_number", "verified_name", "quality_rating")}
            if ok else None, "error": None if ok else cfg.last_error, "config": _config_out(db, h, cfg)}


# ---------------- templates ----------------
def _template_out(t: MessageTemplate, h: Hospital) -> dict:
    if t.requires_approval:
        preview = render_numbered(t.body_text, example_params(t.kind, t.language))
        params = TEMPLATE_PARAMS[t.kind]
    else:
        preview = render_named(t.body_text, {"name": "Ravi", "when": "Wed, 18 Nov, 10:30 AM", "hospital": h.name,
                                             "booking_link": sender.booking_link(h), "hospital_phone": h.phone or ""})
        params = [f"{{{p}}}" for p in REPLY_PLACEHOLDERS]
    return {"id": str(t.id), "kind": t.kind, "language": t.language, "requires_approval": t.requires_approval,
            "meta_template_name": t.meta_template_name, "meta_language_code": t.meta_language_code,
            "category": t.category, "body_text": t.body_text, "button_confirm_text": t.button_confirm_text,
            "button_reschedule_text": t.button_reschedule_text, "approval_status": t.approval_status,
            "rejection_reason": t.rejection_reason, "is_active": t.is_active, "preview": preview,
            "placeholders": params, "updated_at": iso(t.updated_at)}


@router.get("/templates")
def list_templates(current: CurrentUser = Depends(require_hospital("templates:manage")), db: Session = Depends(get_db)):
    h = db.get(Hospital, current.hospital_id)
    rows = db.scalars(select(MessageTemplate).where(MessageTemplate.hospital_id == h.id)
                      .order_by(MessageTemplate.kind, MessageTemplate.language)).all()
    return {"items": [_template_out(t, h) for t in rows]}


class TemplateIn(BaseModel):
    body_text: str | None = Field(default=None, max_length=1024)
    button_confirm_text: str | None = Field(default=None, min_length=1, max_length=25)
    button_reschedule_text: str | None = Field(default=None, min_length=1, max_length=25)
    meta_template_name: str | None = Field(default=None, max_length=120, pattern=r"^[a-z0-9_]+$")
    meta_language_code: str | None = Field(default=None, max_length=10, pattern=r"^[a-z]{2}(_[A-Z]{2})?$")
    approval_status: str | None = Field(default=None, pattern="^(not_submitted|pending|approved|rejected|paused)$")
    is_active: bool | None = None


@router.put("/templates/{template_id}")
def update_template(template_id: uuid.UUID, body: TemplateIn, request: Request,
                    current: CurrentUser = Depends(require_hospital("templates:manage")), db: Session = Depends(get_db)):
    h = db.get(Hospital, current.hospital_id)
    t = get_owned(db, MessageTemplate, template_id, h.id, label="Template")
    data = body.model_dump(exclude_unset=True)
    if "body_text" in data:
        validate_template_body(t.kind, data["body_text"])
        if t.requires_approval and data["body_text"].strip() != t.body_text:
            t.approval_status = "not_submitted"  # changed wording must be approved again
            t.meta_template_id = None
    if not t.requires_approval:
        data = {k: v for k, v in data.items() if k in ("body_text", "is_active")}
    if "approval_status" in data and "body_text" in data and data["body_text"].strip() != t.body_text:
        data.pop("approval_status")
    for k, v in data.items():
        setattr(t, k, v.strip() if isinstance(v, str) else v)
    audit(db, "template.updated", hospital_id=h.id, user_id=current.id, entity_type="template", entity_id=t.id,
          details={"fields": sorted(data)}, ip=client_ip(request))
    db.commit()
    return _template_out(t, h)


def _client(db: Session, h: Hospital):
    cfg = sender.get_config(db, h)
    token = decrypt_secret(cfg.access_token_encrypted)
    if not (cfg.business_account_id and token and cfg.phone_number_id):
        raise ServiceError("Save the WhatsApp business account ID, phone number ID and access token first.")
    return cfg, sender.client_factory(cfg, token)


@router.post("/templates/{template_id}/submit")
def submit_template(template_id: uuid.UUID, request: Request,
                    current: CurrentUser = Depends(require_hospital("templates:manage")), db: Session = Depends(get_db)):
    """Submits the template to WhatsApp for approval (POST /{waba_id}/message_templates)."""
    h = db.get(Hospital, current.hospital_id)
    t = get_owned(db, MessageTemplate, template_id, h.id, label="Template")
    if not t.requires_approval:
        raise ServiceError("Reply messages don't need WhatsApp approval.")
    cfg, client = _client(db, h)
    definition = template_definition(
        name=t.meta_template_name, language_code=t.meta_language_code or t.language, body_text=t.body_text,
        example_params=example_params(t.kind, t.language), buttons=[t.button_confirm_text, t.button_reschedule_text],
        category=t.category)
    with client:
        ok, data = client.create_template(cfg.business_account_id, definition)
    if ok:
        t.meta_template_id = str(data.get("id") or "") or None
        t.approval_status = {"APPROVED": "approved", "REJECTED": "rejected"}.get(data.get("status"), "pending")
        t.rejection_reason = None
    audit(db, "template.submitted", hospital_id=h.id, user_id=current.id, entity_type="template", entity_id=t.id,
          details={"ok": ok}, ip=client_ip(request))
    db.commit()
    if not ok:
        raise ServiceError(f"WhatsApp rejected the submission: {(data.get('error') or {}).get('message', 'unknown error')}", 502)
    return _template_out(t, h)


@router.post("/templates/sync")
def sync_templates(request: Request, current: CurrentUser = Depends(require_hospital("templates:manage")),
                   db: Session = Depends(get_db)):
    """Reads approval status of every template from WhatsApp and updates ours."""
    h = db.get(Hospital, current.hospital_id)
    cfg, client = _client(db, h)
    with client:
        ok, data = client.list_templates(cfg.business_account_id)
    if not ok:
        raise ServiceError(f"Could not read templates from WhatsApp: {(data.get('error') or {}).get('message', '')}", 502)
    remote = {(r.get("name"), r.get("language")): r for r in data.get("data", [])}
    mapping = {"APPROVED": "approved", "PENDING": "pending", "REJECTED": "rejected", "PAUSED": "paused",
               "DISABLED": "paused", "IN_APPEAL": "pending"}
    updated = 0
    for t in db.scalars(select(MessageTemplate).where(MessageTemplate.hospital_id == h.id,
                                                      MessageTemplate.requires_approval.is_(True))).all():
        r = remote.get((t.meta_template_name, t.meta_language_code or t.language))
        if r:
            t.approval_status = mapping.get(r.get("status"), t.approval_status)
            t.meta_template_id = str(r.get("id") or t.meta_template_id or "") or None
            t.rejection_reason = r.get("rejected_reason") if t.approval_status == "rejected" else None
            updated += 1
    audit(db, "template.synced", hospital_id=h.id, user_id=current.id, details={"updated": updated},
          ip=client_ip(request))
    db.commit()
    return {"updated": updated, "items": [_template_out(t, h) for t in db.scalars(
        select(MessageTemplate).where(MessageTemplate.hospital_id == h.id)
        .order_by(MessageTemplate.kind, MessageTemplate.language)).all()]}


# ---------------- message log & reminders ----------------
@router.get("/messages")
def list_messages(status: str | None = None, direction: str | None = Query(default=None, pattern="^(inbound|outbound)$"),
                  page: int = Query(default=1, ge=1), current: CurrentUser = Depends(require_hospital("messages:read")),
                  db: Session = Depends(get_db)):
    stmt = select(WhatsAppMessage, Patient.full_name).outerjoin(Patient, Patient.id == WhatsAppMessage.patient_id) \
        .where(WhatsAppMessage.hospital_id == current.hospital_id)
    if status:
        stmt = stmt.where(WhatsAppMessage.status.in_(status.split(",")))
    if direction:
        stmt = stmt.where(WhatsAppMessage.direction == direction)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(stmt.order_by(WhatsAppMessage.created_at.desc()).offset((page - 1) * 50).limit(50)).all()
    return {"items": [message_out(m, name) for m, name in rows], "total": total}


@router.get("/reminders")
def list_reminders(status: str | None = Query(default=None), page: int = Query(default=1, ge=1),
                   current: CurrentUser = Depends(require_hospital("messages:read")), db: Session = Depends(get_db)):
    stmt = select(ReminderSchedule, Patient.full_name).join(Patient, Patient.id == ReminderSchedule.patient_id) \
        .where(ReminderSchedule.hospital_id == current.hospital_id)
    if status:
        stmt = stmt.where(ReminderSchedule.status.in_(status.split(",")))
    order = ReminderSchedule.due_at if status == "pending" else ReminderSchedule.due_at.desc()
    rows = db.execute(stmt.order_by(order).offset((page - 1) * 50).limit(50)).all()
    counts = dict(db.execute(select(ReminderSchedule.status, func.count()).where(
        ReminderSchedule.hospital_id == current.hospital_id).group_by(ReminderSchedule.status)).all())
    return {"items": [{**reminder_out(r), "patient_name": name, "patient_id": str(r.patient_id),
                       "appointment_id": str(r.appointment_id) if r.appointment_id else None,
                       "follow_up_id": str(r.follow_up_id) if r.follow_up_id else None} for r, name in rows],
            "counts": counts}


@router.post("/reminders/{reminder_id}/retry")
def retry_reminder(reminder_id: uuid.UUID, request: Request,
                   current: CurrentUser = Depends(require_hospital("messages:retry")), db: Session = Depends(get_db)):
    h = db.get(Hospital, current.hospital_id)
    r = db.scalar(select(ReminderSchedule).where(ReminderSchedule.id == reminder_id,
                                                 ReminderSchedule.hospital_id == h.id).with_for_update())
    if r is None:
        raise ServiceError("Reminder not found.", 404)
    result = sender.retry_failed_reminder(db, h, r)
    audit(db, "reminder.retried", hospital_id=h.id, user_id=current.id, entity_type="reminder", entity_id=r.id,
          details={"result": result}, ip=client_ip(request))
    db.commit()
    return {"result": result, "reminder": reminder_out(r)}


class TestMessageIn(BaseModel):
    phone: str = Field(min_length=6, max_length=24)


@router.post("/test-message")
def send_test_message(body: TestMessageIn, request: Request,
                      current: CurrentUser = Depends(require_hospital("whatsapp:manage")), db: Session = Depends(get_db)):
    """Live check: sends the approved appointment template to a phone on the test list only."""
    h = db.get(Hospital, current.hospital_id)
    cfg = sender.get_config(db, h)
    try:
        phone = normalize_phone(body.phone)
    except InvalidPhone as exc:
        raise ServiceError(str(exc)) from exc
    if phone not in (cfg.test_recipient_allowlist or []):
        raise ServiceError("Add this number to the test phone list first. Test messages only go to listed phones.")
    token = decrypt_secret(cfg.access_token_encrypted)
    if not (cfg.phone_number_id and token):
        raise ServiceError("Save the phone number ID and access token first.")
    tpl = db.scalar(select(MessageTemplate).where(MessageTemplate.hospital_id == h.id,
                                                  MessageTemplate.kind == "appointment_reminder",
                                                  MessageTemplate.approval_status == "approved").limit(1))
    if tpl is None:
        raise ServiceError("No approved appointment reminder template yet. Submit it and wait for approval.")
    params = EXAMPLE_PARAMS["appointment_reminder"][:]
    params[1] = h.name
    with sender.client_factory(cfg, token) as client:
        result = client.send_template(to=phone.lstrip("+"), template_name=tpl.meta_template_name,
                                      language_code=tpl.meta_language_code or tpl.language, body_params=params,
                                      button_payloads=["TT1:T:test", "TT1:T:test"])
    now = hospital_now(h)
    msg = WhatsAppMessage(hospital_id=h.id, direction="outbound", message_type="template",
                          template_name=tpl.meta_template_name, language=tpl.meta_language_code, phone_e164=phone,
                          body_preview=render_numbered(tpl.body_text, params),
                          status="accepted" if result.ok else ("unknown" if result.ambiguous else "failed"),
                          wa_message_id=result.wa_message_id, sent_at=now if result.ok else None,
                          error_code=result.error_code, error_message=result.error_message,
                          failed_at=None if result.ok else now)
    db.add(msg)
    audit(db, "whatsapp.test_message", hospital_id=h.id, user_id=current.id, details={"ok": result.ok},
          ip=client_ip(request))
    db.commit()
    return {"ok": result.ok, "message": message_out(msg),
            "error": None if result.ok else f"{result.error_code}: {result.error_message}"}
