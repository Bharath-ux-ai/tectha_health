"""Time helpers. All reminder logic asks the hospital for "now" so demo hospitals can run on a demo clock."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.config import settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def hospital_now(hospital) -> datetime:
    """Current instant for a hospital. Real hospitals always get real time."""
    now = utcnow()
    if hospital.is_demo and settings.ALLOW_DEMO_CLOCK and hospital.demo_clock_offset_seconds:
        return now + timedelta(seconds=hospital.demo_clock_offset_seconds)
    return now


def tz(hospital) -> ZoneInfo:
    return ZoneInfo(hospital.timezone)


def local_today(hospital, now: datetime | None = None) -> date:
    return (now or hospital_now(hospital)).astimezone(tz(hospital)).date()


def local_dt(hospital, d: date, t: time) -> datetime:
    """Aware datetime for a wall-clock date/time at the hospital."""
    return datetime.combine(d, t, tzinfo=tz(hospital))


def to_local(hospital, dt: datetime) -> datetime:
    return dt.astimezone(tz(hospital))


def local_day_bounds(hospital, d: date) -> tuple[datetime, datetime]:
    start = local_dt(hospital, d, time(0, 0))
    return start, local_dt(hospital, d + timedelta(days=1), time(0, 0))


def month_bounds(hospital, month_start: date) -> tuple[datetime, datetime, date, date]:
    first = month_start.replace(day=1)
    nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    return local_dt(hospital, first, time(0, 0)), local_dt(hospital, nxt, time(0, 0)), first, nxt
