"""System admin: hospital onboarding, platform settings, system status. No patient data is exposed here."""
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.common import hospital_out, iso, user_out
from app.config import settings
from app.core.clock import utcnow
from app.core.deps import CurrentUser, client_ip, require
from app.core.errors import NotFound
from app.db import get_db
from app.models import Appointment, Hospital, Patient, ReminderSchedule, SystemSetting, User, WhatsAppConfig
from app.services.audit import audit
from app.services.hospitals import create_hospital

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/hospitals")
def list_hospitals(current: CurrentUser = Depends(require("system:hospitals")), db: Session = Depends(get_db)):
    hospitals = db.scalars(select(Hospital).where(Hospital.deleted_at.is_(None)).order_by(Hospital.name)).all()
    ids = [h.id for h in hospitals]
    counts = lambda model: dict(db.execute(select(model.hospital_id, func.count()).where(  # noqa: E731
        model.hospital_id.in_(ids)).group_by(model.hospital_id)).all()) if ids else {}
    users, patients, appts = counts(User), counts(Patient), counts(Appointment)
    modes = dict(db.execute(select(WhatsAppConfig.hospital_id, WhatsAppConfig.mode)).all())
    month_start = utcnow() - timedelta(days=30)
    recent = dict(db.execute(select(Appointment.hospital_id, func.count()).where(
        Appointment.created_at >= month_start).group_by(Appointment.hospital_id)).all())
    return {"items": [{**hospital_out(h), "users": users.get(h.id, 0), "patients": patients.get(h.id, 0),
                       "appointments": appts.get(h.id, 0), "appointments_30d": recent.get(h.id, 0),
                       "whatsapp_mode": modes.get(h.id, "test")} for h in hospitals]}


class HospitalIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    slug: str | None = Field(default=None, max_length=60)
    address: str | None = Field(default=None, max_length=400)
    phone: str | None = Field(default=None, max_length=32)
    default_language: str = Field(default="en", pattern="^(en|ta)$")
    is_demo: bool = False
    admin_email: EmailStr
    admin_name: str = Field(min_length=2, max_length=120)
    admin_password: str = Field(min_length=1, max_length=200)


@router.post("/hospitals", status_code=201)
def onboard_hospital(body: HospitalIn, request: Request, current: CurrentUser = Depends(require("system:hospitals")),
                     db: Session = Depends(get_db)):
    h, admin = create_hospital(db, name=body.name, slug=body.slug, address=body.address, phone=body.phone,
                               default_language=body.default_language, is_demo=body.is_demo,
                               admin_email=body.admin_email, admin_name=body.admin_name,
                               admin_password=body.admin_password)
    audit(db, "system.hospital_created", hospital_id=h.id, user_id=current.id, entity_type="hospital", entity_id=h.id,
          ip=client_ip(request))
    db.commit()
    return {"hospital": hospital_out(h), "admin": user_out(admin)}


class HospitalUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    is_active: bool | None = None


@router.patch("/hospitals/{hospital_id}")
def update_hospital(hospital_id: uuid.UUID, body: HospitalUpdateIn, request: Request,
                    current: CurrentUser = Depends(require("system:hospitals")), db: Session = Depends(get_db)):
    h = db.get(Hospital, hospital_id)
    if h is None or h.deleted_at:
        raise NotFound("Hospital not found.")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(h, k, v)
    audit(db, "system.hospital_updated", hospital_id=h.id, user_id=current.id, entity_type="hospital", entity_id=h.id,
          details=body.model_dump(exclude_unset=True), ip=client_ip(request))
    db.commit()
    return hospital_out(h)


@router.get("/hospitals/{hospital_id}/admins")
def hospital_admins(hospital_id: uuid.UUID, current: CurrentUser = Depends(require("system:hospitals")),
                    db: Session = Depends(get_db)):
    rows = db.scalars(select(User).where(User.hospital_id == hospital_id, User.role_code == "hospital_admin",
                                         User.deleted_at.is_(None))).all()
    return {"items": [user_out(u) for u in rows]}


@router.get("/status")
def system_status(current: CurrentUser = Depends(require("system:status")), db: Session = Depends(get_db)):
    db_ok = True
    try:
        db.execute(text("select 1"))
    except Exception:  # pragma: no cover
        db_ok = False
    hb = db.get(SystemSetting, "worker_heartbeat")
    hb_at = datetime.fromisoformat(hb.value["at"]) if hb else None
    worker_ok = bool(hb_at and utcnow() - hb_at < timedelta(seconds=settings.WORKER_INTERVAL_SECONDS * 3))
    day_ago = utcnow() - timedelta(days=1)
    by_status = dict(db.execute(select(ReminderSchedule.status, func.count()).where(
        ReminderSchedule.updated_at >= day_ago).group_by(ReminderSchedule.status)).all())
    pending = db.scalar(select(func.count()).select_from(ReminderSchedule).where(ReminderSchedule.status == "pending"))
    overdue = db.scalar(select(func.count()).select_from(ReminderSchedule).join(
        Hospital, Hospital.id == ReminderSchedule.hospital_id).where(
        ReminderSchedule.status == "pending", Hospital.is_demo.is_(False),
        ReminderSchedule.due_at < utcnow() - timedelta(minutes=15)))
    return {
        "database": db_ok, "worker": {"ok": worker_ok, "last_heartbeat": iso(hb_at),
                                      "last_run": hb.value.get("last_run") if hb else None},
        "reminders_24h": by_status, "reminders_pending": pending, "reminders_overdue": overdue,
        "hospitals": db.scalar(select(func.count()).select_from(Hospital).where(Hospital.deleted_at.is_(None))),
        "live_messaging_enabled": _live_enabled(db), "environment": settings.APP_ENV,
        "whatsapp_platform": {"app_secret_set": bool(settings.WHATSAPP_APP_SECRET),
                              "verify_token_set": bool(settings.WHATSAPP_VERIFY_TOKEN),
                              "graph_version": settings.WHATSAPP_GRAPH_VERSION},
    }


def _live_enabled(db: Session) -> bool:
    row = db.get(SystemSetting, "live_messaging_enabled")
    return True if row is None else bool(row.value.get("enabled", True))


class SettingsIn(BaseModel):
    live_messaging_enabled: bool


@router.get("/settings")
def get_settings_(current: CurrentUser = Depends(require("system:settings")), db: Session = Depends(get_db)):
    return {"live_messaging_enabled": _live_enabled(db)}


@router.put("/settings")
def put_settings(body: SettingsIn, request: Request, current: CurrentUser = Depends(require("system:settings")),
                 db: Session = Depends(get_db)):
    row = db.get(SystemSetting, "live_messaging_enabled")
    if row is None:
        db.add(SystemSetting(key="live_messaging_enabled", value={"enabled": body.live_messaging_enabled},
                             updated_by_user_id=current.id))
    else:
        row.value, row.updated_by_user_id, row.updated_at = {"enabled": body.live_messaging_enabled}, current.id, utcnow()
    audit(db, "system.settings_updated", user_id=current.id, details=body.model_dump(), ip=client_ip(request))
    db.commit()
    return {"live_messaging_enabled": body.live_messaging_enabled}
