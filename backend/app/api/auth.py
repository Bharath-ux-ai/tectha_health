from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.common import hospital_out, user_out
from app.config import settings
from app.core.clock import utcnow
from app.core.deps import CurrentUser, client_ip, get_current_user, permission_map
from app.core.ratelimit import forgot_limiter, login_limiter
from app.core.security import (
    create_access_token, hash_password, new_url_token, sha256_hex, validate_password_strength, verify_password,
)
from app.db import get_db
from app.models import Hospital, PasswordResetToken, User
from app.services.audit import audit
from app.services.emailer import send_email

router = APIRouter(prefix="/api/auth", tags=["auth"])

GENERIC_LOGIN_ERROR = "Email or password is incorrect."


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class ForgotIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(settings.COOKIE_NAME, token, max_age=settings.JWT_EXPIRE_MINUTES * 60, httponly=True,
                        secure=settings.COOKIE_SECURE, samesite="lax", path="/")


def me_payload(db: Session, current: CurrentUser) -> dict:
    hospital = db.get(Hospital, current.hospital_id) if current.hospital_id else None
    return {"user": user_out(current.user), "permissions": sorted(current.permissions),
            "hospital": hospital_out(hospital) if hospital else None}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = client_ip(request)
    login_limiter.check(f"{ip}:{body.email.lower()}")
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.lower(), User.deleted_at.is_(None)))
    now = utcnow()
    if user is None:
        verify_password(body.password, "$2b$12$" + "x" * 53)  # equalise timing
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, GENERIC_LOGIN_ERROR)
    if user.locked_until and user.locked_until > now:
        raise HTTPException(status.HTTP_423_LOCKED, "Too many failed attempts. Try again in a few minutes or reset your password.")
    if not verify_password(body.password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= settings.MAX_FAILED_LOGINS:
            user.locked_until = now + timedelta(minutes=settings.LOCKOUT_MINUTES)
            user.failed_login_count = 0
            audit(db, "auth.locked", hospital_id=user.hospital_id, user_id=user.id, ip=ip)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, GENERIC_LOGIN_ERROR)
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account is deactivated. Ask your hospital admin.")
    if user.hospital_id:
        h = db.get(Hospital, user.hospital_id)
        if not h or not h.is_active or h.deleted_at:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "This hospital account is inactive.")
    user.failed_login_count, user.locked_until, user.last_login_at = 0, None, now
    token = create_access_token(user_id=str(user.id), hospital_id=str(user.hospital_id) if user.hospital_id else None,
                                role=user.role_code, token_version=user.token_version)
    audit(db, "auth.login", hospital_id=user.hospital_id, user_id=user.id, ip=ip)
    db.commit()
    _set_session_cookie(response, token)
    return {"user": user_out(user), "permissions": sorted(permission_map(db).get(user.role_code, [])),
            "hospital": hospital_out(db.get(Hospital, user.hospital_id)) if user.hospital_id else None}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(settings.COOKIE_NAME, path="/")
    return {"ok": True}


@router.post("/logout-all")
def logout_all(response: Response, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    current.user.token_version += 1
    db.commit()
    response.delete_cookie(settings.COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return me_payload(db, current)


@router.post("/forgot-password")
def forgot_password(body: ForgotIn, request: Request, db: Session = Depends(get_db)):
    forgot_limiter.check(client_ip(request) or "unknown")
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.lower(), User.deleted_at.is_(None),
                                        User.is_active.is_(True)))
    if user:
        raw = new_url_token()
        db.add(PasswordResetToken(user_id=user.id, token_hash=sha256_hex(raw),
                                  expires_at=utcnow() + timedelta(minutes=settings.PASSWORD_RESET_MINUTES)))
        audit(db, "auth.reset_requested", hospital_id=user.hospital_id, user_id=user.id, ip=client_ip(request))
        db.commit()
        link = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/reset-password?token={raw}"
        send_email(user.email, "Reset your TEC THA password",
                   f"Hello {user.full_name},\n\nUse this link within {settings.PASSWORD_RESET_MINUTES} minutes to set a "
                   f"new password:\n{link}\n\nIf you didn't ask for this, ignore this email.")
    # Same answer whether or not the account exists.
    return {"ok": True, "message": "If an account exists for that email, a reset link is on its way."}


@router.post("/reset-password")
def reset_password(body: ResetIn, request: Request, db: Session = Depends(get_db)):
    row = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == sha256_hex(body.token)))
    if row is None or row.used_at is not None or row.expires_at < utcnow():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This reset link is invalid or has expired. Request a new one.")
    try:
        validate_password_strength(body.new_password)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    user = db.get(User, row.user_id)
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1  # signs out every existing session
    user.failed_login_count, user.locked_until = 0, None
    row.used_at = utcnow()
    audit(db, "auth.password_reset", hospital_id=user.hospital_id, user_id=user.id, ip=client_ip(request))
    db.commit()
    return {"ok": True}


@router.post("/change-password")
def change_password(body: ChangePasswordIn, response: Response, current: CurrentUser = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    user = current.user
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect.")
    try:
        validate_password_strength(body.new_password)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1
    audit(db, "auth.password_changed", hospital_id=user.hospital_id, user_id=user.id)
    db.commit()
    token = create_access_token(user_id=str(user.id), hospital_id=str(user.hospital_id) if user.hospital_id else None,
                                role=user.role_code, token_version=user.token_version)
    _set_session_cookie(response, token)
    return {"ok": True}
