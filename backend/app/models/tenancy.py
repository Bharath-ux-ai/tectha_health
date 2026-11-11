"""Hospitals, users, roles/permissions, platform settings."""
import uuid
from datetime import datetime, time

from sqlalchemy import (
    JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, Time, Uuid, text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import IdMixin, SoftDeleteMixin, TimestampMixin


class Hospital(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "hospitals"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    address: Mapped[str | None] = mapped_column(String(400))
    phone: Mapped[str | None] = mapped_column(String(32))
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Kolkata")
    default_language: Mapped[str] = mapped_column(String(5), nullable=False, default="en")
    appointment_reminder_time: Mapped[time] = mapped_column(Time, nullable=False, default=time(18, 0))
    followup_reminder_time: Mapped[time] = mapped_column(Time, nullable=False, default=time(10, 0))
    booking_horizon_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    min_booking_lead_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Demo clock: offset applied to real time for demo hospitals only (never for real hospitals).
    demo_clock_offset_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        CheckConstraint("default_language in ('en','ta')", name="ck_hospitals_language"),
        CheckConstraint("booking_horizon_days between 1 and 180", name="ck_hospitals_horizon"),
    )

    whatsapp_config: Mapped["WhatsAppConfig | None"] = relationship(back_populates="hospital", uselist=False)


class WhatsAppConfig(TimestampMixin, Base):
    __tablename__ = "whatsapp_configs"

    hospital_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("hospitals.id", ondelete="CASCADE"), primary_key=True)
    mode: Mapped[str] = mapped_column(String(10), nullable=False, default="test")  # disabled | test | live
    phone_number_id: Mapped[str | None] = mapped_column(String(40))
    business_account_id: Mapped[str | None] = mapped_column(String(40))
    display_phone_number: Mapped[str | None] = mapped_column(String(32))
    access_token_encrypted: Mapped[str | None] = mapped_column(Text)
    test_recipient_allowlist: Mapped[list[str]] = mapped_column(ARRAY(String(20)), nullable=False, default=list)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)

    hospital: Mapped[Hospital] = relationship(back_populates="whatsapp_config")

    __table_args__ = (
        CheckConstraint("mode in ('disabled','test','live')", name="ck_whatsapp_mode"),
        Index("uq_whatsapp_phone_number_id", "phone_number_id", unique=True,
              postgresql_where=text("phone_number_id is not null")),
    )


class Role(Base):
    __tablename__ = "roles"
    code: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300))


class Permission(Base):
    __tablename__ = "permissions"
    code: Mapped[str] = mapped_column(String(60), primary_key=True)
    description: Mapped[str | None] = mapped_column(String(300))


class RolePermission(Base):
    __tablename__ = "role_permissions"
    role_code: Mapped[str] = mapped_column(String(40), ForeignKey("roles.code", ondelete="CASCADE"), primary_key=True)
    permission_code: Mapped[str] = mapped_column(
        String(60), ForeignKey("permissions.code", ondelete="CASCADE"), primary_key=True
    )


class User(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "users"

    hospital_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("hospitals.id", ondelete="RESTRICT"))
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    role_code: Mapped[str] = mapped_column(String(40), ForeignKey("roles.code"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    hospital: Mapped[Hospital | None] = relationship()

    __table_args__ = (
        Index("uq_users_email", text("lower(email)"), unique=True, postgresql_where=text("deleted_at is null")),
        Index("ix_users_hospital", "hospital_id"),
        CheckConstraint(
            "(role_code = 'system_admin' and hospital_id is null) or (role_code <> 'system_admin' and hospital_id is not null)",
            name="ck_users_role_scope",
        ),
    )


class PasswordResetToken(IdMixin, Base):
    __tablename__ = "password_reset_tokens"
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class SystemSetting(Base):
    __tablename__ = "system_settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))


class AuditLog(IdMixin, Base):
    __tablename__ = "audit_logs"
    hospital_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("hospitals.id", ondelete="SET NULL"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict | None] = mapped_column(JSON)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (Index("ix_audit_hospital_created", "hospital_id", "created_at"),)
