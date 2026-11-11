import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.clock import hospital_now
from app.core.deps import CurrentUser, client_ip, require_hospital
from app.db import get_db
from app.models import Hospital
from app.services import demo, engine
from app.services.audit import audit

router = APIRouter(prefix="/api/demo", tags=["demo"])


def _h(db: Session, current: CurrentUser) -> Hospital:
    h = db.get(Hospital, current.hospital_id)
    demo.require_demo(h)
    return h


@router.get("")
def state(current: CurrentUser = Depends(require_hospital("demo:manage")), db: Session = Depends(get_db)):
    return demo.state(db, _h(db, current))


class ClockIn(BaseModel):
    local_datetime: datetime  # wall-clock time at the hospital, e.g. 2026-11-17T18:05


@router.post("/clock")
def set_clock(body: ClockIn, current: CurrentUser = Depends(require_hospital("demo:manage")),
              db: Session = Depends(get_db)):
    h = _h(db, current)
    demo.set_clock(db, h, body.local_datetime.replace(tzinfo=None))
    db.commit()
    return demo.state(db, h)


@router.post("/clock/real")
def real_clock(current: CurrentUser = Depends(require_hospital("demo:manage")), db: Session = Depends(get_db)):
    h = _h(db, current)
    h.demo_clock_offset_seconds = 0
    db.commit()
    return demo.state(db, h)


@router.post("/run-engine")
def run_engine(current: CurrentUser = Depends(require_hospital("demo:manage")), db: Session = Depends(get_db)):
    h = _h(db, current)
    stats = engine.run_hospital(db, h)
    db.commit()
    return {"engine": stats, "now": hospital_now(h).isoformat()}


class StepIn(BaseModel):
    key: str = Field(max_length=30)


@router.post("/step")
def run_step(body: StepIn, request: Request, current: CurrentUser = Depends(require_hospital("demo:manage")),
             db: Session = Depends(get_db)):
    h = _h(db, current)
    result = demo.run_step(db, h, body.key, user_id=current.id)
    audit(db, "demo.step", hospital_id=h.id, user_id=current.id, details={"step": body.key}, ip=client_ip(request))
    db.commit()
    return {"result": result, "state": demo.state(db, h)}


class ResetIn(BaseModel):
    start_monday: date | None = None


@router.post("/reset")
def reset(body: ResetIn, request: Request, current: CurrentUser = Depends(require_hospital("demo:manage")),
          db: Session = Depends(get_db)):
    h = _h(db, current)
    demo.reset(db, h, body.start_monday)
    audit(db, "demo.reset", hospital_id=h.id, user_id=current.id, ip=client_ip(request))
    db.commit()
    return demo.state(db, h)


class SimulateIn(BaseModel):
    message_id: uuid.UUID
    action: str = Field(pattern="^(C|R)$")


@router.post("/simulate-reply")
def simulate(body: SimulateIn, current: CurrentUser = Depends(require_hospital("demo:manage")),
             db: Session = Depends(get_db)):
    h = _h(db, current)
    outcome = demo.simulate_reply(db, h, body.message_id, body.action)
    db.commit()
    return {"outcome": outcome, "state": demo.state(db, h)}
