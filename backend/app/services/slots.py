"""Slot generation from doctors' weekly availability."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import hospital_now, local_day_bounds, local_dt, local_today, tz
from app.models import ACTIVE_APPOINTMENT_STATUSES, Appointment, Doctor, DoctorAvailability, Hospital


@dataclass
class Slot:
    start_at: datetime
    end_at: datetime
    available: bool


def _utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc)


def day_slots(db: Session, hospital: Hospital, doctor: Doctor, d: date, *, now: datetime | None = None,
              lead_minutes: int | None = None) -> list[Slot]:
    now = now or hospital_now(hospital)
    lead = hospital.min_booking_lead_minutes if lead_minutes is None else lead_minutes
    earliest = now + timedelta(minutes=lead)
    blocks = db.scalars(select(DoctorAvailability).where(
        DoctorAvailability.doctor_id == doctor.id, DoctorAvailability.weekday == d.weekday())).all()
    if not blocks:
        return []
    start, end = local_day_bounds(hospital, d)
    taken = {_utc(s) for s in db.scalars(select(Appointment.start_at).where(
        Appointment.doctor_id == doctor.id, Appointment.start_at >= start, Appointment.start_at < end,
        Appointment.status.in_(ACTIVE_APPOINTMENT_STATUSES)))}
    seen: dict[datetime, Slot] = {}
    for b in blocks:
        step = timedelta(minutes=b.slot_minutes)
        cur, block_end = local_dt(hospital, d, b.start_time), local_dt(hospital, d, b.end_time)
        while cur + step <= block_end:
            key = _utc(cur)
            if key not in seen:
                seen[key] = Slot(start_at=cur, end_at=cur + step, available=key not in taken and cur >= earliest)
            cur += step
    return [seen[k] for k in sorted(seen)]


def bookable_dates(db: Session, hospital: Hospital, doctor: Doctor) -> list[dict]:
    now = hospital_now(hospital)
    today = local_today(hospital, now)
    out = []
    weekdays = {w for (w,) in db.execute(select(DoctorAvailability.weekday).where(
        DoctorAvailability.doctor_id == doctor.id)).all()}
    for i in range(hospital.booking_horizon_days + 1):
        d = today + timedelta(days=i)
        if d.weekday() not in weekdays:
            continue
        open_count = sum(1 for s in day_slots(db, hospital, doctor, d, now=now) if s.available)
        out.append({"date": d.isoformat(), "open_slots": open_count})
    return out


def find_slot(db: Session, hospital: Hospital, doctor: Doctor, start_at: datetime, *, lead_minutes: int | None = None,
              now: datetime | None = None) -> Slot | None:
    local_date = start_at.astimezone(tz(hospital)).date()
    for s in day_slots(db, hospital, doctor, local_date, now=now, lead_minutes=lead_minutes):
        if _utc(s.start_at) == _utc(start_at):
            return s
    return None
