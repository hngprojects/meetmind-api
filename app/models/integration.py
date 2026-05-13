import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey


class UserPlatformIntegration(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "user_platform_integrations"
    __table_args__ = (UniqueConstraint("user_id", "platform"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    platform: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str | None] = mapped_column(String(20), default="disconnected")
    access_token: Mapped[str | None] = mapped_column(Text)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime)


class Integration(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "integrations"
    __table_args__ = (UniqueConstraint("workspace_id", "provider"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str | None] = mapped_column(String(20), default="connected")
    phase: Mapped[str | None] = mapped_column(String(10))
    access_token: Mapped[str | None] = mapped_column(Text)
    config: Mapped[str | None] = mapped_column(Text)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime)


class IntegrationChannel(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "integration_channels"

    integration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("integrations.id"), nullable=False
    )
    channel_id: Mapped[str] = mapped_column(String(100), nullable=False)
    channel_name: Mapped[str | None] = mapped_column(String(100))
    ai_enabled: Mapped[bool | None] = mapped_column(Boolean, default=True)


class IntegrationSettings(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "integration_settings"

    integration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("integrations.id"), nullable=False
    )
    ai_behavior: Mapped[str | None] = mapped_column(String(30))
    response_mode: Mapped[str | None] = mapped_column(String(20))
    show_reason: Mapped[bool | None] = mapped_column(Boolean, default=True)
    show_confidence: Mapped[bool | None] = mapped_column(Boolean, default=True)
    tag_ai_responses: Mapped[bool | None] = mapped_column(Boolean, default=True)
    capture_decisions: Mapped[bool | None] = mapped_column(Boolean, default=True)
    capture_action_items: Mapped[bool | None] = mapped_column(Boolean, default=True)
    summary_frequency: Mapped[str | None] = mapped_column(String(20))
    summary_channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("integration_channels.id")
    )


class WaitlistSignup(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "waitlist_signups"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    email: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True,
    )
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime)
