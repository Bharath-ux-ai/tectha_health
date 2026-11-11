"""Hospital profile & reminder settings, doctors & weekly schedules, staff accounts, audit log."""
import uuid
from datetime import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.common import doctor_out, hospital_out, user_out
from app.core.clock import utcnow
from app.core.deps import CurrentUser, client_ip, get_owned, require_hospital
from app.core.errors import ServiceError
from app.core.security import hash_password, validate_password_strength
from app.db import get_db
from app.models import AuditLog, Doctor, DoctorAvailability, Hospital, User
from app.services import reminders
from app.services.audit import audit
from app.services.hospitals import create_user

router = APIRouter(prefix="/api", tags=["hospital"])


# ---------------- hospital profile ----------------
@router.get("/hospital")
def get_hospital(current: CurrentUser = Depends(require_hospital("hospital:read")), db: Session = Depends(get_db)):
    return hospital_out(db.get(Hospital, current.hospital_id))


class HospitalUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    address: str | None = Field(default=None, max_length=400)
    phone: str | None = Field(default=None, max_length=32)
    timezone: str | None = Field(default=None, max_length=64)
    default_language: str | None = Field(default=None, pattern="^(en|ta)$")
    appointment_reminder_time: time | None = None
    followup_reminder_time: time | None = None
    booking_horizon_days: int | None = Field(default=None, ge=1, le=180)
    min_booking_lead_minutes: int | None = Field(default=None, ge=0, le=1440)

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v):
        if v is None:
            return v
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Unknown timezone")
        return v


@router.patch("/hospital")
def update_hospital(body: HospitalUpdateIn, request: Request,
                    current: CurrentUser = Depends(require_hospital("hospital:manage")), db: Session = Depends(get_db)):
    h = db.get(Hospital, current.hospital_id)
    changes = body.model_dump(exclude_unset=True)
    times_changed = False
    for k, v in changes.items():
        if k in ("appointment_reminder_time", "followup_reminder_time", "timezone") and getattr(h, k) != v:
            times_changed = True
        setattr(h, k, v)
    if times_changed:
        db.flush()
        reminders.reschedule_for_hospital_settings(db, h)
    audit(db, "hospital.updated", hospital_id=h.id, user_id=current.id, entity_type="hospital", entity_id=h.id,
          details={k: str(v) for k, v in changes.items()}, ip=client_ip(request))
    db.commit()
    return hospital_out(h)


# ---------------- doctors ----------------
@router.get("/doctors")
def list_doctors(include_inactive: bool = False, current: CurrentUser = Depends(require_hospital("doctors:read")),
                 db: Session = Depends(get_db)):
    q = select(Doctor).options(selectinload(Doctor.availability)).where(
        Doctor.hospital_id == current.hospital_id, Doctor.deleted_at.is_(None))
    if not include_inactive:
        q = q.where(Doctor.is_active.is_(True))
    return {"items": [doctor_out(d) for d in db.scalars(q.order_by(Doctor.name)).all()]}


class DoctorIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    specialty: str | None = Field(default=None, max_length=120)
    is_active: bool = True


@router.post("/doctors", status_code=201)
def create_doctor(body: DoctorIn, request: Request, current: CurrentUser = Depends(require_hospital("doctors:manage")),
                  db: Session = Depends(get_db)):
    d = Doctor(hospital_id=current.hospital_id, name=body.name.strip(),
               specialty=(body.specialty or "").strip() or None, is_active=body.is_active)
    db.add(d)
    db.flush()
    audit(db, "doctor.created", hospital_id=current.hospital_id, user_id=current.id, entity_type="doctor",
          entity_id=d.id, ip=client_ip(request))
    db.commit()
    db.refresh(d)
    return doctor_out(d)


class DoctorUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    specialty: str | None = Field(default=None, max_length=120)
    is_active: bool | None = None


@router.patch("/doctors/{doctor_id}")
def update_doctor(doctor_id: uuid.UUID, body: DoctorUpdateIn, request: Request,
                  current: CurrentUser = Depends(require_hospital("doctors:manage")), db: Session = Depends(get_db)):
    d = get_owned(db, Doctor, doctor_id, current.hospital_id, label="Doctor")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(d, k, v.strip() if isinstance(v, str) else v)
    audit(db, "doctor.updated", hospital_id=current.hospital_id, user_id=current.id, entity_type="doctor",
          entity_id=d.id, ip=client_ip(request))
    db.commit()
    db.refresh(d)
    return doctor_out(d)


@router.delete("/doctors/{doctor_id}")
def delete_doctor(doctor_id: uuid.UUID, request: Request,
                  current: CurrentUser = Depends(require_hospital("doctors:manage")), db: Session = Depends(get_db)):
    d = get_owned(db, Doctor, doctor_id, current.hospital_id, label="Doctor")
    d.deleted_at, d.is_active = utcnow(), False  # soft delete keeps appointment history intact
    audit(db, "doctor.removed", hospital_id=current.hospital_id, user_id=current.id, entity_type="doctor",
          entity_id=d.id, ip=client_ip(request))
    db.commit()
    return {"ok": True}


class AvailabilityBlock(BaseModel):
    weekday: int = Field(ge=0, le=6)
    start_time: time
    end_time: time
    slot_minutes: int = Field(default=15, ge=5, le=240)


class AvailabilityIn(BaseModel):
    blocks: list[AvailabilityBlock] = Field(max_length=42)


@router.put("/doctors/{doctor_id}/availability")
def set_availability(doctor_id: uuid.UUID, body: AvailabilityIn, request: Request,
                     current: CurrentUser = Depends(require_hospital("doctors:manage")), db: Session = Depends(get_db)):
    d = get_owned(db, Doctor, doctor_id, current.hospital_id, label="Doctor")
    by_day: dict[int, list[AvailabilityBlock]] = {}
    for b in body.blocks:
        if b.end_time <= b.start_time:
            raise ServiceError("Each session must end after it starts.")
        by_day.setdefault(b.weekday, []).append(b)
    for blocks in by_day.values():
        blocks.sort(key=lambda b: b.start_time)
        for a, b in zip(blocks, blocks[1:], strict=False):
            if b.start_time < a.end_time:
                raise ServiceError("Sessions on the same day overlap.")
    d.availability.clear()
    db.flush()
    for b in body.blocks:
        d.availability.append(DoctorAvailability(hospital_id=d.hospital_id, weekday=b.weekday, start_time=b.start_time,
                                                 end_time=b.end_time, slot_minutes=b.slot_minutes))
    audit(db, "doctor.schedule_updated", hospital_id=current.hospital_id, user_id=current.id, entity_type="doctor",
          entity_id=d.id, details={"blocks": len(body.blocks)}, ip=client_ip(request))
    db.commit()
    db.refresh(d)
    return doctor_out(d)


# ---------------- staff ----------------
@router.get("/staff")
def list_staff(current: CurrentUser = Depends(require_hospital("staff:manage")), db: Session = Depends(get_db)):
    rows = db.scalars(select(User).where(User.hospital_id == current.hospital_id, User.deleted_at.is_(None))
                      .order_by(User.full_name)).all()
    return {"items": [user_out(u) for u in rows]}


class StaffIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=120)
    role: str = Field(pattern="^(hospital_admin|staff)$")
    password: str = Field(min_length=1, max_length=200)


@router.post("/staff", status_code=201)
def create_staff(body: StaffIn, request: Request, current: CurrentUser = Depends(require_hospital("staff:manage")),
                 db: Session = Depends(get_db)):
    u = create_user(db, email=body.email, full_name=body.full_name, password=body.password, role_code=body.role,
                    hospital_id=current.hospital_id)
    audit(db, "staff.created", hospital_id=current.hospital_id, user_id=current.id, entity_type="user",
          entity_id=u.id, details={"role": body.role}, ip=client_ip(request))
    db.commit()
    return user_out(u)


class StaffUpdateIn(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    role: str | None = Field(default=None, pattern="^(hospital_admin|staff)$")
    is_active: bool | None = None


@router.patch("/staff/{user_id}")
def update_staff(user_id: uuid.UUID, body: StaffUpdateIn, request: Request,
                 current: CurrentUser = Depends(require_hospital("staff:manage")), db: Session = Depends(get_db)):
    u = get_owned(db, User, user_id, current.hospital_id, label="Staff member")
    if u.id == current.id and (body.is_active is False or (body.role and body.role != u.role_code)):
        raise ServiceError("You can't deactivate or change the role of your own account.")
    if body.full_name is not None:
        u.full_name = body.full_name.strip()
    if body.role is not None and body.role != u.role_code:
        u.role_code = body.role
        u.token_version += 1
    if body.is_active is not None and body.is_active != u.is_active:
        u.is_active = body.is_active
        u.token_version += 1  # deactivation ends existing sessions immediately
    audit(db, "staff.updated", hospital_id=current.hospital_id, user_id=current.id, entity_type="user",
          entity_id=u.id, details=body.model_dump(exclude_unset=True), ip=client_ip(request))
    db.commit()
    return user_out(u)


class TempPasswordIn(BaseModel):
    password: str = Field(min_length=1, max_length=200)


@router.post("/staff/{user_id}/password")
def set_staff_password(user_id: uuid.UUID, body: TempPasswordIn, request: Request,
                       current: CurrentUser = Depends(require_hospital("staff:manage")), db: Session = Depends(get_db)):
    u = get_owned(db, User, user_id, current.hospital_id, label="Staff member")
    try:
        validate_password_strength(body.password)
    except ValueError as exc:
        raise ServiceError(str(exc)) from exc
    u.password_hash = hash_password(body.password)
    u.token_version += 1
    u.failed_login_count, u.locked_until = 0, None
    audit(db, "staff.password_set", hospital_id=current.hospital_id, user_id=current.id, entity_type="user",
          entity_id=u.id, ip=client_ip(request))
    db.commit()
    return {"ok": True}


# ---------------- audit log ----------------
@router.get("/audit-logs")
def audit_logs(limit: int = Query(default=100, le=500), current: CurrentUser = Depends(require_hospital("audit:read")),
               db: Session = Depends(get_db)):
    rows = db.execute(select(AuditLog, User.full_name).outerjoin(User, User.id == AuditLog.user_id)
                      .where(AuditLog.hospital_id == current.hospital_id)
                      .order_by(AuditLog.created_at.desc()).limit(limit)).all()
    return {"items": [{"id": str(a.id), "action": a.action, "entity_type": a.entity_type, "entity_id": a.entity_id,
                       "details": a.details, "user": name, "ip": a.ip_address, "at": a.created_at.isoformat()}
                      for a, name in rows]}
