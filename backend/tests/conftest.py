"""Test fixtures. Tests run against a real PostgreSQL database (TEST_DATABASE_URL), built with the Alembic
migrations, so partial unique indexes, row locking and constraints are exercised for real."""
import os

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://tectha:tectha_dev_pw@localhost:5432/tectha_test")
os.environ["APP_ENV"] = "test"
os.environ["PUBLIC_BASE_URL"] = "https://app.test"
os.environ["WHATSAPP_APP_SECRET"] = "test-app-secret"
os.environ["WHATSAPP_VERIFY_TOKEN"] = "test-verify-token"
os.environ["ALLOW_DEMO_CLOCK"] = "true"

import hashlib  # noqa: E402
import hmac  # noqa: E402
import json  # noqa: E402
from datetime import date, datetime, time, timedelta, timezone  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core import clock  # noqa: E402
from app.core.deps import reset_permission_cache  # noqa: E402
from app.core.ratelimit import booking_limiter, forgot_limiter, login_limiter, public_read_limiter  # noqa: E402
from app.core.security import encrypt_secret  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Doctor, DoctorAvailability, MessageTemplate, WhatsAppConfig  # noqa: E402
from app.services.hospitals import create_hospital, create_user  # noqa: E402
from app.services.whatsapp import sender  # noqa: E402
from app.services.whatsapp.client import WhatsAppCloudClient  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
PASSWORD = "Str0ngPassw0rd"
KEEP_TABLES = {"roles", "permissions", "role_permissions", "alembic_version"}


@pytest.fixture(scope="session", autouse=True)
def migrated_db():
    with engine.begin() as conn:
        conn.execute(text("drop schema public cascade; create schema public;"))
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    command.upgrade(cfg, "head")
    reset_permission_cache()
    yield


@pytest.fixture(autouse=True)
def clean_tables(migrated_db):
    with engine.begin() as conn:
        tables = [r[0] for r in conn.execute(text(
            "select tablename from pg_tables where schemaname='public'")).all() if r[0] not in KEEP_TABLES]
        conn.execute(text("truncate " + ", ".join(tables) + " restart identity cascade"))
    for limiter in (booking_limiter, public_read_limiter, login_limiter, forgot_limiter):
        limiter.reset()
    yield


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


class Clock:
    """Freezes 'now' for every hospital (real ones included) by patching the clock module."""

    def __init__(self, monkeypatch):
        self.mp = monkeypatch
        self.current = None

    def set(self, local: datetime):
        aware = local if local.tzinfo else local.replace(tzinfo=IST)
        self.current = aware.astimezone(timezone.utc)
        self.mp.setattr(clock, "utcnow", lambda: self.current)
        return self.current

    def advance(self, **kw):
        return self.set(self.current + timedelta(**kw))


@pytest.fixture
def frozen(monkeypatch):
    c = Clock(monkeypatch)
    c.set(datetime(2026, 11, 16, 9, 0))  # Monday
    return c


def make_hospital(db, slug: str, *, doctors: int = 1):
    h, admin = create_hospital(db, name=f"Hospital {slug}", slug=slug, address="Coimbatore", phone="+914224000000",
                               admin_email=f"admin@{slug}.clinic.in", admin_name="Admin", admin_password=PASSWORD)
    staff = create_user(db, email=f"staff@{slug}.clinic.in", full_name="Reception", password=PASSWORD, role_code="staff",
                        hospital_id=h.id)
    docs = []
    for i in range(doctors):
        d = Doctor(hospital_id=h.id, name=f"Dr. Test {i + 1}", specialty="General")
        db.add(d)
        db.flush()
        for wd in range(6):
            db.add(DoctorAvailability(hospital_id=h.id, doctor_id=d.id, weekday=wd, start_time=time(9, 0),
                                      end_time=time(13, 0), slot_minutes=15))
        docs.append(d)
    db.commit()
    return h, admin, staff, docs


@pytest.fixture
def hosp(db):
    return make_hospital(db, "alpha")


@pytest.fixture
def other_hosp(db):
    return make_hospital(db, "beta")


class ApiClient:
    def __init__(self):
        self.c = TestClient(app)
        self.c.headers.update({"X-Requested-With": "tectha"})

    def login(self, email, password=PASSWORD):
        r = self.c.post("/api/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        return self

    def __getattr__(self, item):
        return getattr(self.c, item)


@pytest.fixture
def api():
    return ApiClient


def at(d: date, hh: int, mm: int = 0) -> str:
    return datetime.combine(d, time(hh, mm), tzinfo=IST).isoformat()


# ---------- WhatsApp live-mode helpers ----------
class FakeMeta:
    """Stands in for graph.facebook.com in tests via httpx.MockTransport. Records every request."""

    def __init__(self):
        self.requests: list[dict] = []
        self.responses: list = []  # queue of (status, json) or Exception instances
        self.counter = 0

    def handler(self, request: httpx.Request):
        body = json.loads(request.content or b"{}")
        self.requests.append({"url": str(request.url), "method": request.method, "json": body})
        if self.responses:
            nxt = self.responses.pop(0)
            if isinstance(nxt, Exception):
                raise nxt
            status, data = nxt
            return httpx.Response(status, json=data)
        self.counter += 1
        return httpx.Response(200, json={"messaging_product": "whatsapp", "contacts": [{"wa_id": body.get("to")}],
                                         "messages": [{"id": f"wamid.TEST{self.counter}"}]})

    @property
    def sends(self):
        return [r for r in self.requests if r["url"].endswith("/messages")]


@pytest.fixture
def meta(monkeypatch):
    fake = FakeMeta()
    monkeypatch.setattr(sender, "client_factory", lambda cfg, token: WhatsAppCloudClient(
        phone_number_id=cfg.phone_number_id, access_token=token, transport=httpx.MockTransport(fake.handler)))
    return fake


def go_live(db, hospital, phone_number_id="1111", approve=True, allowlist=None):
    cfg = db.get(WhatsAppConfig, hospital.id)
    cfg.mode = "live"
    cfg.phone_number_id = phone_number_id
    cfg.business_account_id = "2222"
    cfg.access_token_encrypted = encrypt_secret("EAATESTTOKEN")
    cfg.test_recipient_allowlist = allowlist or []
    if approve:
        for t in db.query(MessageTemplate).filter_by(hospital_id=hospital.id, requires_approval=True):
            t.approval_status = "approved"
    db.commit()
    return cfg


def signed(payload: dict) -> tuple[bytes, dict]:
    raw = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(b"test-app-secret", raw, hashlib.sha256).hexdigest()
    return raw, {"X-Hub-Signature-256": sig, "Content-Type": "application/json"}


def wh_envelope(phone_number_id: str, *, statuses=None, messages=None) -> dict:
    value = {"messaging_product": "whatsapp", "metadata": {"display_phone_number": "914224000000",
                                                            "phone_number_id": phone_number_id}}
    if statuses:
        value["statuses"] = statuses
    if messages:
        value["messages"] = messages
    return {"object": "whatsapp_business_account",
            "entry": [{"id": "2222", "changes": [{"field": "messages", "value": value}]}]}
