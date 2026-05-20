import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey


class User(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "users"

    name: Mapped[str | None] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    work_email: Mapped[str | None] = mapped_column(String(255))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    job_title: Mapped[str | None] = mapped_column(String(80))
    company: Mapped[str | None] = mapped_column(String(120))
    role: Mapped[str | None] = mapped_column(String(60))
    language: Mapped[str | None] = mapped_column(String(20), default="en")
    hires: Mapped[str | None] = mapped_column(String(30))
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)


class UserTrial(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "user_trials"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, unique=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RefreshToken(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked: Mapped[bool | None] = mapped_column(Boolean, default=False)


class SSOProvider(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "sso_providers"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(255), nullable=False)


class PasswordResetToken(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "password_reset_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ActiveSession(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "active_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    refresh_token_hash: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True
    )
    device_hint: Mapped[str | None] = mapped_column(String(120))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserMeetingPreferences(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "user_meeting_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    unlimited_transcripts: Mapped[bool | None] = mapped_column(Boolean, default=True)
    join_condition: Mapped[str | None] = mapped_column(String(40))
    send_recap_to: Mapped[str | None] = mapped_column(String(40))
    auto_record: Mapped[bool | None] = mapped_column(Boolean, default=False)
    announce: Mapped[bool | None] = mapped_column(Boolean, default=False)


class UserInterviewPreferences(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "user_interview_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    default_interview_type: Mapped[str | None] = mapped_column(String(120))
    default_duration_min: Mapped[int | None] = mapped_column(Integer, default=60)
    evaluation_focus: Mapped[str | None] = mapped_column(Text)
    tone: Mapped[str | None] = mapped_column(String(80))


class UserNotificationPreferences(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "user_notification_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    interview_goes_live: Mapped[bool | None] = mapped_column(Boolean, default=True)
    interview_completed: Mapped[bool | None] = mapped_column(Boolean, default=True)
    weekly_digest: Mapped[bool | None] = mapped_column(Boolean, default=True)
    product_updates: Mapped[bool | None] = mapped_column(Boolean, default=True)


class UserPrivacySettings(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "user_privacy_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    require_approval_before_sharing: Mapped[bool | None] = mapped_column(
        Boolean, default=True
    )
    hide_private_manager_notes: Mapped[bool | None] = mapped_column(
        Boolean, default=True
    )


class UserSecuritySettings(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "user_security_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    two_factor_enabled: Mapped[bool | None] = mapped_column(Boolean, default=False)
    two_factor_secret: Mapped[str | None] = mapped_column(Text)
