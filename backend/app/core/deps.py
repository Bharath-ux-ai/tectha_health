"""Request dependencies: authentication, CSRF protection, permissions, tenant scoping."""
import threading
import uuid
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.security import decode_access_token
from app.db import get_db
from app.models import Hospital, RolePermission, User

_perm_lock = threading.Lock()
_perm_cache: dict[str, frozenset[str]] | None = None

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def permission_map(db: Session) -> dict[str, frozenset[str]]:
    global _perm_cache
    if _perm_cache is None:
        with _perm_lock:
            if _perm_cache is None:
                rows = db.execute(select(RolePermission.role_code, RolePermission.permission_code)).all()
                acc: dict[str, set[str]] = {}
                for role, perm in rows:
                    acc.setdefault(role, set()).add(perm)
                _perm_cache = {k: frozenset(v) for k, v in acc.items()}
    return _perm_cache


def reset_permission_cache() -> None:
    global _perm_cache
    _perm_cache = None


@dataclass
class CurrentUser:
    user: User
    permissions: frozenset[str]

    @property
    def id(self) -> uuid.UUID:
        return self.user.id

    @property
    def hospital_id(self) -> uuid.UUID | None:
        return self.user.hospital_id

    @property
    def role(self) -> str:
        return self.user.role_code

    def can(self, perm: str) -> bool:
        return perm in self.permissions


def _unauthorized(detail: str = "Sign in to continue.") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> CurrentUser:
    token = None
    via_cookie = False
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    else:
        token = request.cookies.get(settings.COOKIE_NAME)
        via_cookie = token is not None
    if not token:
        raise _unauthorized()
    # Cookie sessions must send the custom header on state-changing requests. Cross-site forms cannot set it,
    # and CORS only lets our own frontend origin add it — this blocks CSRF.
    if via_cookie and request.method not in SAFE_METHODS and request.headers.get("x-requested-with") != "tectha":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Missing request header.")
    try:
        payload = decode_access_token(token)
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise _unauthorized("Your session has expired. Sign in again.")
    user = db.get(User, user_id)
    if not user or not user.is_active or user.deleted_at is not None or payload.get("tv") != user.token_version:
        raise _unauthorized("Your session has expired. Sign in again.")
    if user.hospital_id is not None:
        hospital = db.get(Hospital, user.hospital_id)
        if not hospital or not hospital.is_active or hospital.deleted_at is not None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="This hospital account is inactive.")
    return CurrentUser(user=user, permissions=permission_map(db).get(user.role_code, frozenset()))


def require(*perms: str):
    def checker(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        missing = [p for p in perms if not current.can(p)]
        if missing:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="You don't have permission to do this.")
        return current

    return checker


def require_hospital(*perms: str):
    """Permission check plus guarantee that the user belongs to a hospital (tenant)."""
    base = require(*perms)

    def checker(current: CurrentUser = Depends(base)) -> CurrentUser:
        if current.hospital_id is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="This action is only available to hospital accounts.")
        return current

    return checker


def get_owned(db: Session, model, obj_id: uuid.UUID, hospital_id: uuid.UUID, *, label: str = "Record"):
    """Fetch a tenant-owned row. Rows of other hospitals are reported as not found (no existence leak)."""
    obj = db.get(model, obj_id)
    if obj is None or getattr(obj, "hospital_id", None) != hospital_id or getattr(obj, "deleted_at", None) is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{label} not found.")
    return obj


def client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None
