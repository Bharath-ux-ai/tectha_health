"""Message templates, reminder schedules, WhatsApp messages, delivery logs, inbound webhook log, reports."""
import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text, Uuid, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import IdMixin, TimestampMixin

TEMPLATE_KINDS = ("appointment_reminder", "followup_reminder", "confirm_reply", "reschedule_reply")
REMINDER_KINDS = ("appointment_day_before", "followup_7d", "followup_3d")


class MessageTemplate(IdMixin, TimestampMixin, Base):
    __tablename__ = "message_templates"
    hospital_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    language: Mapped[str] = mapped_column(String(5), nullable=False)  # en | ta
    # Meta-approved template (reminders) vs. free-form session reply (sent only inside the 24h service window)
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    meta_template_name: Mapped[str | None] = mapped_column(String(120))
    meta_language_code: Mapped[str | None] = mapped_column(String(10))
    category: Mapped[str] = mapped_column(String(20), nullable=False, default="UTILITY")
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    button_confirm_text: Mapped[str | None] = mapped_column(String(25))
    button_reschedule_text: Mapped[str | None] = mapped_column(String(25))
    approval_status: Mapped[str] = mapped_column(String(20), nullable=False, default="not_submitted")
    meta_template_id: Mapped[str | None] = mapped_column(String(40))
    rejection_reason: Mapped[str | None] = mapped_column(String(300))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        CheckConstraint(
            "kind in ('appointment_reminder','followup_reminder','confirm_reply','reschedule_reply')",
            name="ck_templates_kind",
        ),
        CheckConstraint("language in ('en','ta')", name="ck_templates_language"),
        CheckConstraint(
            "approval_status in ('not_submitted','pending','approved','rejected','paused','not_required')",
            name="ck_templates_approval",
        ),
        Index("uq_templates_kind_lang", "hospital_id", "kind", "language", unique=True),
    )


class ReminderSchedule(IdMixin, TimestampMixin, Base):
    __tablename__ = "reminder_schedules"
    hospital_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("appointments.id", ondelete="CASCADE"))
    follow_up_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("follow_ups.id", ondelete="CASCADE"))
    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # pending | processing | sent | simulated | skipped | failed | cancelled
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    # Unique per target + target date + kind: re-scheduling to the same date can never create a second reminder.
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    skip_reason: Mapped[str | None] = mapped_column(String(60))
    last_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("kind in ('appointment_day_before','followup_7d','followup_3d')", name="ck_reminders_kind"),
        CheckConstraint(
            "status in ('pending','processing','sent','simulated','skipped','failed','cancelled')",
            name="ck_reminders_status",
        ),
        CheckConstraint(
            "(appointment_id is not null and follow_up_id is null) or (appointment_id is null and follow_up_id is not null)",
            name="ck_reminders_target",
        ),
        Index("ix_reminders_due", "status", "due_at"),
        Index("ix_reminders_hospital", "hospital_id", "status"),
        Index("ix_reminders_appointment", "appointment_id"),
        Index("ix_reminders_follow_up", "follow_up_id"),
    )


class WhatsAppMessage(IdMixin, TimestampMixin, Base):
    __tablename__ = "whatsapp_messages"
    hospital_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    patient_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("patients.id", ondelete="SET NULL"))
    reminder_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("reminder_schedules.id", ondelete="SET NULL"))
    reply_to_message_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("whatsapp_messages.id", ondelete="SET NULL"))
    direction: Mapped[str] = mapped_column(String(8), nullable=False)  # outbound | inbound
    message_type: Mapped[str] = mapped_column(String(16), nullable=False)  # template | text | button
    template_name: Mapped[str | None] = mapped_column(String(120))
    language: Mapped[str | None] = mapped_column(String(10))
    phone_e164: Mapped[str] = mapped_column(String(20), nullable=False)
    body_preview: Mapped[str | None] = mapped_column(Text)
    payload_ref: Mapped[str | None] = mapped_column(String(40), unique=True)  # opaque token placed in button payloads
    wa_message_id: Mapped[str | None] = mapped_column(String(200))
    # outbound: accepted | sent | delivered | read | failed | simulated | unknown ; inbound: received
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    is_simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    error_code: Mapped[str | None] = mapped_column(String(20))
    error_message: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    events: Mapped[list["MessageEvent"]] = relationship(
        back_populates="message", cascade="all, delete-orphan", order_by="MessageEvent.occurred_at"
    )

    __table_args__ = (
        Index("uq_messages_wamid", "wa_message_id", unique=True, postgresql_where=text("wa_message_id is not null")),
        Index("ix_messages_hospital_created", "hospital_id", "created_at"),
        Index("ix_messages_reminder", "reminder_id"),
        Index("ix_messages_patient", "patient_id"),
    )


class MessageEvent(IdMixin, Base):
    """Delivery log: every API response and webhook status for a message."""
    __tablename__ = "message_events"
    hospital_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    message_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("whatsapp_messages.id", ondelete="CASCADE"), nullable=False)
    event: Mapped[str] = mapped_column(String(30), nullable=False)
    detail: Mapped[dict | None] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    message: Mapped[WhatsAppMessage] = relationship(back_populates="events")

    __table_args__ = (Index("ix_message_events_message", "message_id"),)


class WebhookEvent(IdMixin, Base):
    """Raw inbound webhook items. dedupe_key makes Meta's redeliveries harmless."""
    __tablename__ = "webhook_events"
    hospital_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("hospitals.id", ondelete="SET NULL"))
    dedupe_key: Mapped[str] = mapped_column(String(240), nullable=False, unique=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    outcome: Mapped[str | None] = mapped_column(String(80))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class MonthlyReport(IdMixin, Base):
    __tablename__ = "monthly_reports"
    hospital_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    month: Mapped[date] = mapped_column(Date, nullable=False)  # first day of month
    data: Mapped[dict] = mapped_column(JSON, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    generated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))

    __table_args__ = (Index("uq_monthly_reports", "hospital_id", "month", unique=True),)
