from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from sdk.db import SDKBase
from sdk.security import decrypt_secret, encrypt_secret


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SDKSession(SDKBase):
    __tablename__ = "sdk_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    platform: Mapped[str] = mapped_column(String(30), nullable=False)
    meeting_id: Mapped[str | None] = mapped_column(String(255))
    meeting_url: Mapped[str | None] = mapped_column(Text)
    agent_name: Mapped[str] = mapped_column(String(120), nullable=False)
    context: Mapped[str | None] = mapped_column(Text)
    wake_words_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="created")
    provider_session_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    @property
    def wake_words(self) -> list[str]:
        return json.loads(self.wake_words_json or "[]")

    def set_wake_words(self, wake_words: list[str]) -> None:
        self.wake_words_json = json.dumps(wake_words)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "platform": self.platform,
            "meeting_id": self.meeting_id,
            "meeting_url": self.meeting_url,
            "agent_name": self.agent_name,
            "context": self.context,
            "wake_words": self.wake_words,
            "status": self.status,
            "provider_session_id": self.provider_session_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class SDKTranscriptTurn(SDKBase):
    __tablename__ = "sdk_transcript_turns"
    __table_args__ = (UniqueConstraint("session_id", "sequence_no"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    platform: Mapped[str] = mapped_column(String(30), nullable=False)
    source: Mapped[str] = mapped_column(String(60), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="human")
    speaker_name: Mapped[str | None] = mapped_column(String(255))
    speaker_id: Mapped[str | None] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp_ms: Mapped[int | None] = mapped_column(Integer)
    provider_stream_id: Mapped[str | None] = mapped_column(String(255))
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    trigger_reason: Mapped[str | None] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "platform": self.platform,
            "source": self.source,
            "role": self.role,
            "speaker_name": self.speaker_name,
            "speaker_id": self.speaker_id,
            "content": self.content,
            "timestamp_ms": self.timestamp_ms,
            "provider_stream_id": self.provider_stream_id,
            "sequence_no": self.sequence_no,
            "trigger_reason": self.trigger_reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class SDKProviderEvent(SDKBase):
    __tablename__ = "sdk_provider_events"
    __table_args__ = (UniqueConstraint("provider", "event_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    event_id: Mapped[str | None] = mapped_column(String(255))
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    session_id: Mapped[str | None] = mapped_column(String, index=True)
    provider_stream_id: Mapped[str | None] = mapped_column(String(255))
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "provider": self.provider,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "session_id": self.session_id,
            "provider_stream_id": self.provider_stream_id,
            "payload": json.loads(self.payload_json),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class SDKZoomOAuthToken(SDKBase):
    __tablename__ = "sdk_zoom_oauth_tokens"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    zoom_user_id: Mapped[str | None] = mapped_column(String(255), index=True)
    access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text)
    token_type: Mapped[str] = mapped_column(
        String(60), nullable=False, default="bearer"
    )
    scope: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    @property
    def access_token(self) -> str:
        value = decrypt_secret(self.access_token_encrypted)
        if value is None:
            raise ValueError("Stored Zoom access token is empty.")
        return value

    @access_token.setter
    def access_token(self, value: str) -> None:
        encrypted_value = encrypt_secret(value)
        if encrypted_value is None:
            raise ValueError("Zoom access token cannot be empty.")
        self.access_token_encrypted = encrypted_value

    @property
    def refresh_token(self) -> str | None:
        return decrypt_secret(self.refresh_token_encrypted)

    @refresh_token.setter
    def refresh_token(self, value: str | None) -> None:
        self.refresh_token_encrypted = encrypt_secret(value)
