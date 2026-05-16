from __future__ import annotations

import json
from collections import defaultdict
from threading import Lock

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sdk.config import get_sdk_settings
from sdk.models import SDKProviderEvent, SDKSession, SDKTranscriptTurn
from sdk.wake_words import normalize_wake_words

_sequence_locks: defaultdict[str, Lock] = defaultdict(Lock)


class SDKRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_session(
        self,
        *,
        platform: str,
        meeting_id: str | None,
        meeting_url: str | None,
        agent_name: str,
        context: str | None,
        wake_words: list[str] | None,
    ) -> SDKSession:
        configured_wake_words = normalize_wake_words(
            wake_words or get_sdk_settings().zoom_default_wake_words
        )
        session = SDKSession(
            platform=platform,
            meeting_id=meeting_id,
            meeting_url=meeting_url,
            agent_name=agent_name,
            context=context,
        )
        session.set_wake_words(configured_wake_words)
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def get_session(self, session_id: str) -> SDKSession | None:
        return self.db.get(SDKSession, session_id)

    def find_zoom_session(self, meeting_id: str | None) -> SDKSession | None:
        if not meeting_id:
            return None
        return self.db.execute(
            select(SDKSession)
            .where(SDKSession.platform == "zoom")
            .where(SDKSession.meeting_id == str(meeting_id))
            .order_by(SDKSession.created_at.desc())
        ).scalar_one_or_none()

    def update_session_status(
        self,
        session: SDKSession,
        status: str,
        provider_session_id: str | None = None,
    ) -> SDKSession:
        session.status = status
        if provider_session_id:
            session.provider_session_id = provider_session_id
        self.db.commit()
        self.db.refresh(session)
        return session

    def add_transcript_turn(
        self,
        *,
        session: SDKSession,
        source: str,
        role: str,
        speaker_name: str | None,
        speaker_id: str | None,
        content: str,
        timestamp_ms: int | None,
        provider_stream_id: str | None,
        trigger_reason: str | None = None,
    ) -> SDKTranscriptTurn:
        with _sequence_locks[session.id]:
            for _ in range(3):
                sequence_no = self.next_sequence(session.id)
                turn = SDKTranscriptTurn(
                    session_id=session.id,
                    platform=session.platform,
                    source=source,
                    role=role,
                    speaker_name=speaker_name,
                    speaker_id=speaker_id,
                    content=content,
                    timestamp_ms=timestamp_ms,
                    provider_stream_id=provider_stream_id,
                    sequence_no=sequence_no,
                    trigger_reason=trigger_reason,
                )
                self.db.add(turn)
                try:
                    self.db.commit()
                except IntegrityError:
                    self.db.rollback()
                    continue
                self.db.refresh(turn)
                return turn
        raise RuntimeError("Could not assign transcript sequence number.")

    def list_transcript(self, session_id: str) -> list[SDKTranscriptTurn]:
        return list(
            self.db.execute(
                select(SDKTranscriptTurn)
                .where(SDKTranscriptTurn.session_id == session_id)
                .order_by(SDKTranscriptTurn.sequence_no.asc())
            ).scalars()
        )

    def record_provider_event(
        self,
        *,
        provider: str,
        event_id: str | None,
        event_type: str,
        session_id: str | None,
        provider_stream_id: str | None,
        payload: dict,
    ) -> SDKProviderEvent:
        event = SDKProviderEvent(
            provider=provider,
            event_id=event_id,
            event_type=event_type,
            session_id=session_id,
            provider_stream_id=provider_stream_id,
            payload_json=json.dumps(payload),
        )
        self.db.add(event)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            if event_id is None:
                raise
            existing = (
                self.db.execute(
                    select(SDKProviderEvent)
                    .where(SDKProviderEvent.provider == provider)
                    .where(SDKProviderEvent.event_id == event_id)
                    .limit(1)
                )
                .scalars()
                .first()
            )
            if existing is None:
                raise
            return existing
        self.db.refresh(event)
        return event

    def next_sequence(self, session_id: str) -> int:
        value = self.db.execute(
            select(func.coalesce(func.max(SDKTranscriptTurn.sequence_no), 0) + 1).where(
                SDKTranscriptTurn.session_id == session_id
            )
        ).scalar_one()
        return int(value)
