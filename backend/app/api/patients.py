import uuid

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api.common import appointment_out, followup_out, message_out, patient_out
from app.core.clock import local_today
from app.core.deps import CurrentUser, client_ip, get_owned, require_hospital
from app.core.errors import ServiceError
from app.core.phone import InvalidPhone, normalize_name, normalize_phone
from app.db import get_db
from app.models import Appointment, ContactLog, FollowUp, Hospital, Patient, PatientConsent, User, WhatsAppMessage
from app.services import patients as patient_svc
from app.services.audit import audit
from app.services.followups import attention_for, failed_reminder_followup_ids

router = APIRouter(prefix="/api/patients", tags=["patients"])


@router.get("")
def search(q: str | None = Query(default=None, max_length=80), page: int = Query(default=1, ge=1),
           current: CurrentUser = Depends(require_hospital("patients:read")), db: Session = Depends(get_db)):
    stmt = select(Patient).where(Patient.hospital_id == current.hospital_id, Patient.deleted_at.is_(None))
    if q and q.strip():
        digits = "".join(c for c in q if c.isdigit())
        conds = [Patient.name_normalized.like(f"%{normalize_name(q)}%")]
        if len(digits) >= 4:
            conds.append(Patient.phone_e164.like(f"%{digits}%"))
        stmt = stmt.where(or_(*conds))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Patient.full_name).offset((page - 1) * 50).limit(50)).all()
    last_visit = {}
    if rows:
        for pid, at in db.execute(select(Appointment.patient_id, func.max(Appointment.start_at)).where(
                Appointment.patient_id.in_([p.id for p in rows])).group_by(Appointment.patient_id)).all():
            last_visit[pid] = at.isoformat()
    return {"items": [{**patient_out(p), "last_appointment_at": last_visit.get(p.id)} for p in rows], "total": total}


@router.get("/{patient_id}")
def detail(patient_id: uuid.UUID, request: Request, current: CurrentUser = Depends(require_hospital("patients:read")),
           db: Session = Depends(get_db)):
    h = db.get(Hospital, current.hospital_id)
    p = get_owned(db, Patient, patient_id, h.id, label="Patient")
    appts = db.scalars(select(Appointment).options(selectinload(Appointment.patient), selectinload(Appointment.doctor))
                       .where(Appointment.patient_id == p.id).order_by(Appointment.start_at.desc())).all()
    fus = db.scalars(select(FollowUp).options(selectinload(FollowUp.patient), selectinload(FollowUp.doctor))
                     .where(FollowUp.patient_id == p.id).order_by(FollowUp.due_date.desc())).all()
    today = local_today(h)
    failed = failed_reminder_followup_ids(db, list(fus))
    msgs = db.scalars(select(WhatsAppMessage).where(WhatsAppMessage.patient_id == p.id)
                      .order_by(WhatsAppMessage.created_at.desc()).limit(50)).all()
    consents = db.scalars(select(PatientConsent).where(PatientConsent.patient_id == p.id)
                          .order_by(PatientConsent.created_at.desc())).all()
    contacts = db.execute(select(ContactLog, User.full_name).outerjoin(User, User.id == ContactLog.user_id)
                          .where(ContactLog.patient_id == p.id).order_by(ContactLog.created_at.desc()).limit(50)).all()
    audit(db, "patient.viewed", hospital_id=h.id, user_id=current.id, entity_type="patient", entity_id=p.id,
          ip=client_ip(request))
    db.commit()
    return {
        **patient_out(p),
        "appointments": [appointment_out(h, a) for a in appts],
        "follow_ups": [_with_attention(f, today, f.id in failed) for f in fus],
        "messages": [message_out(m) for m in msgs],
        "consents": [{"granted": c.granted, "source": c.source, "at": c.created_at.isoformat(),
                      "version": c.consent_text_version} for c in consents],
        "contacts": [{"id": str(c.id), "method": c.method, "outcome": c.outcome, "note": c.note,
                      "at": c.created_at.isoformat(), "by": name, "follow_up_id": str(c.follow_up_id) if c.follow_up_id else None}
                     for c, name in contacts],
    }


def _with_attention(fu, today, failed: bool) -> dict:
    att = attention_for(fu, today, failed)
    return {**followup_out(fu), "attention": att.level, "attention_reason": att.reason}


class PatientUpdateIn(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    phone: str | None = Field(default=None, min_length=6, max_length=24)
    preferred_language: str | None = Field(default=None, pattern="^(en|ta)$")
    whatsapp_opt_in: bool | None = None


@router.patch("/{patient_id}")
def update(patient_id: uuid.UUID, body: PatientUpdateIn, request: Request,
           current: CurrentUser = Depends(require_hospital("patients:write")), db: Session = Depends(get_db)):
    h = db.get(Hospital, current.hospital_id)
    p = get_owned(db, Patient, patient_id, h.id, label="Patient")
    changes = {}
    if body.full_name is not None and body.full_name.strip() != p.full_name:
        p.full_name = " ".join(body.full_name.split())
        p.name_normalized = normalize_name(p.full_name)
        changes["full_name"] = True
    if body.phone is not None:
        try:
            e164 = normalize_phone(body.phone)
        except InvalidPhone as exc:
            raise ServiceError(str(exc)) from exc
        if e164 != p.phone_e164:
            p.phone_e164 = e164
            changes["phone"] = True
    if changes:
        clash = db.scalar(select(Patient.id).where(Patient.hospital_id == h.id, Patient.id != p.id,
                                                   Patient.phone_e164 == p.phone_e164,
                                                   Patient.name_normalized == p.name_normalized,
                                                   Patient.deleted_at.is_(None)))
        if clash:
            raise ServiceError("Another patient record already has this name and phone number.", 409)
    if body.preferred_language and body.preferred_language != p.preferred_language:
        p.preferred_language = body.preferred_language
        changes["preferred_language"] = body.preferred_language
    if body.whatsapp_opt_in is not None and body.whatsapp_opt_in != p.whatsapp_opt_in:
        patient_svc.set_consent(db, p, body.whatsapp_opt_in, source="staff_update", user_id=current.id)
        changes["whatsapp_opt_in"] = body.whatsapp_opt_in
    if changes:
        audit(db, "patient.updated", hospital_id=h.id, user_id=current.id, entity_type="patient", entity_id=p.id,
              details=changes, ip=client_ip(request))
    db.commit()
    return patient_out(p)
