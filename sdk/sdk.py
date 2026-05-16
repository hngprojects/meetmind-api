from __future__ import annotations

from sqlalchemy.orm import Session

from sdk.models import SDKSession, SDKTranscriptTurn
from sdk.repositories import SDKRepository


class MeetMindSDK:
    """Developer-facing Python SDK service for meeting agent sessions."""

    def __init__(self, db: Session):
        self.repository = SDKRepository(db)

    def create_zoom_session(
        self,
        *,
        meeting_id: str | None,
        meeting_url: str | None,
        agent_name: str,
        context: str | None = None,
        wake_words: list[str] | None = None,
    ) -> SDKSession:
        return self.repository.create_session(
            platform="zoom",
            meeting_id=meeting_id,
            meeting_url=meeting_url,
            agent_name=agent_name,
            context=context,
            wake_words=wake_words,
        )

    def get_session(self, session_id: str) -> SDKSession | None:
        return self.repository.get_session(session_id)

    def get_transcript(self, session_id: str) -> list[SDKTranscriptTurn]:
        return self.repository.list_transcript(session_id)
