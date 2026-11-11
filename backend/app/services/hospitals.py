"""Hospital onboarding (system admin) and user helpers."""
import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, ServiceError
from app.core.security import hash_password, validate_password_strength
from app.models import Hospital, User, WhatsAppConfig
from app.services.templates import seed_default_templates

SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,58}[a-z0-9])$")
RESERVED_SLUGS = {"admin", "api", "login", "system", "demo", "static", "book"}


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:60] or "hospital"


def validate_slug(slug: str) -> str:
    slug = slug.strip().lower()
    if not SLUG_RE.match(slug) or slug in RESERVED_SLUGS:
        raise ServiceError("Booking link name must be 3–60 characters: lowercase letters, numbers and dashes.")
    return slug


def create_user(db: Session, *, email: str, full_name: str, password: str, role_code: str,
                hospital_id: uuid.UUID | None) -> User:
    email = email.strip().lower()
    if db.scalar(select(User.id).where(func.lower(User.email) == email, User.deleted_at.is_(None))):
        raise Conflict("An account with this email already exists.", code="email_taken")
    try:
        validate_password_strength(password)
    except ValueError as exc:
        raise ServiceError(str(exc)) from exc
    user = User(email=email, full_name=full_name.strip(), password_hash=hash_password(password),
                role_code=role_code, hospital_id=hospital_id)
    db.add(user)
    db.flush()
    return user


def create_hospital(db: Session, *, name: str, slug: str | None, address: str | None, phone: str | None,
                    timezone: str = "Asia/Kolkata", default_language: str = "en", is_demo: bool = False,
                    admin_email: str, admin_name: str, admin_password: str) -> tuple[Hospital, User]:
    slug = validate_slug(slug or slugify(name))
    if db.scalar(select(Hospital.id).where(Hospital.slug == slug)):
        raise Conflict("That booking link name is already used by another hospital.", code="slug_taken")
    hospital = Hospital(name=name.strip(), slug=slug, address=address, phone=phone, timezone=timezone,
                        default_language=default_language, is_demo=is_demo)
    db.add(hospital)
    db.flush()
    db.add(WhatsAppConfig(hospital_id=hospital.id, mode="test", test_recipient_allowlist=[]))
    seed_default_templates(db, hospital)
    admin = create_user(db, email=admin_email, full_name=admin_name, password=admin_password,
                        role_code="hospital_admin", hospital_id=hospital.id)
    return hospital, admin
