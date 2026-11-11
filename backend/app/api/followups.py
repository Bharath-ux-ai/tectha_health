import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.api.appointments import reminder_out
from app.api.common import followup_out
from app.core.clock import local_today
from app.core.deps import CurrentUser, client_ip, get_owned, require_hospital
from app.core.errors import ServiceError
from app.core.phone import normalize_name
from app.db import get_db
from app.models import OPEN_FOLLOWUP_STATUSES, Appointment, ContactLog, FollowUp, Hospital, Patient, ReminderSchedule
from app.services import followups as svc
from app.services.audit import audit
from app.services.dashboard import followup_rows

router = APIRouter(prefix="/api/followups", tags=["follow-ups"])


@router.get("")
def list_followups(
    view: str = Query(default="open", pattern="^(attention|open|upcoming|missed|completed|all)$"),
    date_from: date | None = None, date_to: date | None = None, q: str | None = Query(default=None, max_length=80),
    current: CurrentUser = Depends(require_hospital("followups:read")), db: Session = Depends(get_db),
):
    h = db.get(Hospital, current.hospital_id)
    today = local_today(h)
    stmt = (select(FollowUp).join(Patient, Patient.id == FollowUp.patient_id)
            .options(selectinload(FollowUp.patient), selectinload(FollowUp.doctor))
            .where(FollowUp.hospital_id == h.id))
    if view in ("open", "attention"):
        stmt = stmt.where(or_(FollowUp.status.in_(OPEN_FOLLOWUP_STATUSES), FollowUp.status == "missed"))
    elif view == "upcoming":
        stmt = stmt.where(FollowUp.status.in_(OPEN_FOLLOWUP_STATUSES), FollowUp.due_date >= today)
    elif view == "missed":
        stmt = stmt.where(FollowUp.status == "missed")
    elif view == "completed":
        stmt = stmt.where(FollowUp.status == "completed")
    if date_from:
        stmt = stmt.where(FollowUp.due_date >= date_from)
    if date_to:
        stmt = stmt.where(FollowUp.due_date <= date_to)
    if q and q.strip():
        digits = "".join(c for c in q if c.isdigit())
        conds = [Patient.name_normalized.like(f"%{normalize_name(q)}%")]
        if len(digits) >= 4:
            conds.append(Patient.phone_e164.like(f"%{digits}%"))
        stmt = stmt.where(or_(*conds))
    rows = db.scalars(stmt.order_by(FollowUp.due_date).limit(500)).all()
    items = followup_rows(db, h, list(rows), today)
    if view == "attention":
        items = [i for i in items if i["attention"]]
    elif view != "all":
        items.sort(key=lambda r: ({"red": 0, "amber": 1, None: 2}[r["attention"]], r["due_date"]))
    return {"items": items, "today": today.isoformat()}


class FollowUpIn(BaseModel):
    patient_id: uuid.UUID
    due_date: date
    source_appointment_id: uuid.UUID | None = None
    doctor_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=300)


@router.post("", status_code=201)
def create(body: FollowUpIn, request: Request, current: CurrentUser = Depends(require_hospital("followups:write")),
           db: Session = Depends(get_db)):
    h = db.get(Hospital, current.hospital_id)
    patient = get_owned(db, Patient, body.patient_id, h.id, label="Patient")
    appt = get_owned(db, Appointment, body.source_appointment_id, h.id, label="Appointment") \
        if body.source_appointment_id else None
    if body.doctor_id:
        from app.services.booking import get_doctor
        get_doctor(db, h, body.doctor_id)
    fu = svc.create_followup(db, h, patient=patient, due_date=body.due_date, source_appointment=appt,
                             doctor_id=body.doctor_id, note=body.note, user_id=current.id)
    audit(db, "followup.created", hospital_id=h.id, user_id=current.id, entity_type="follow_up", entity_id=fu.id,
          details={"due_date": body.due_date.isoformat()}, ip=client_ip(request))
    db.commit()
    db.refresh(fu)
    return _detail(db, h, fu)


def _detail(db: Session, h: Hospital, fu: FollowUp) -> dict:
    reminders = db.scalars(select(ReminderSchedule).where(ReminderSchedule.follow_up_id == fu.id)
                           .order_by(ReminderSchedule.due_at)).all()
    contacts = db.scalars(select(ContactLog).where(ContactLog.follow_up_id == fu.id)
                          .order_by(ContactLog.created_at.desc())).all()
    today = local_today(h)
    att = svc.attention_for(fu, today, fu.id in svc.failed_reminder_followup_ids(db, [fu]))
    return {**followup_out(fu), "attention": att.level, "attention_reason": att.reason,
            "days_to_due": (fu.due_date - today).days,
            "reminders": [reminder_out(r) for r in reminders],
            "contacts": [{"id": str(c.id), "method": c.method, "outcome": c.outcome, "note": c.note,
                          "at": c.created_at.isoformat()} for c in contacts]}


@router.get("/{fu_id}")
def get(fu_id: uuid.UUID, current: CurrentUser = Depends(require_hospital("followups:read")),
        db: Session = Depends(get_db)):
    h = db.get(Hospital, current.hospital_id)
    return _detail(db, h, get_owned(db, FollowUp, fu_id, h.id, label="Follow-up"))


class RescheduleIn(BaseModel):
    due_date: date


@router.post("/{fu_id}/reschedule")
def reschedule(fu_id: uuid.UUID, body: RescheduleIn, request: Request,
               current: CurrentUser = Depends(require_hospital("followups:write")), db: Session = Depends(get_db)):
    h = db.get(Hospital, current.hospital_id)
    fu = get_owned(db, FollowUp, fu_id, h.id, label="Follow-up")
    old = fu.due_date.isoformat()
    svc.reschedule_followup(db, h, fu, body.due_date)
    audit(db, "followup.rescheduled", hospital_id=h.id, user_id=current.id, entity_type="follow_up", entity_id=fu.id,
          details={"from": old, "to": body.due_date.isoformat()}, ip=client_ip(request))
    db.commit()
    return _detail(db, h, fu)


class StatusIn(BaseModel):
    status: str = Field(pattern="^(scheduled|confirmed|completed|missed|cancelled)$")


@router.post("/{fu_id}/status")
def set_status(fu_id: uuid.UUID, body: StatusIn, request: Request,
               current: CurrentUser = Depends(require_hospital("followups:write")), db: Session = Depends(get_db)):
    h = db.get(Hospital, current.hospital_id)
    fu = get_owned(db, FollowUp, fu_id, h.id, label="Follow-up")
    old = fu.status
    svc.change_followup_status(db, h, fu, body.status)
    audit(db, "followup.status", hospital_id=h.id, user_id=current.id, entity_type="follow_up", entity_id=fu.id,
          details={"from": old, "to": body.status}, ip=client_ip(request))
    db.commit()
    return _detail(db, h, fu)


class ContactIn(BaseModel):
    method: str = Field(pattern="^(phone|whatsapp|in_person)$")
    outcome: str = Field(pattern="^(reached|no_answer|wrong_number|will_visit|declined)$")
    note: str | None = Field(default=None, max_length=300)


@router.post("/{fu_id}/contacts", status_code=201)
def log_contact(fu_id: uuid.UUID, body: ContactIn, request: Request,
                current: CurrentUser = Depends(require_hospital("followups:write")), db: Session = Depends(get_db)):
    h = db.get(Hospital, current.hospital_id)
    fu = get_owned(db, FollowUp, fu_id, h.id, label="Follow-up")
    if fu.status in ("completed", "cancelled"):
        raise ServiceError("This follow-up is closed.")
    db.add(ContactLog(hospital_id=h.id, patient_id=fu.patient_id, follow_up_id=fu.id, user_id=current.id,
                      method=body.method, outcome=body.outcome, note=(body.note or "").strip() or None))
    if body.outcome == "will_visit" and fu.status in ("scheduled", "reschedule_requested") \
            and fu.due_date >= local_today(h) - timedelta(days=0):
        svc.change_followup_status(db, h, fu, "confirmed")
    audit(db, "followup.contact_logged", hospital_id=h.id, user_id=current.id, entity_type="follow_up",
          entity_id=fu.id, details={"method": body.method, "outcome": body.outcome}, ip=client_ip(request))
    db.commit()
    return _detail(db, h, fu)
