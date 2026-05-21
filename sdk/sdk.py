from __future__ import annotations

from sqlalchemy.orm import Session

from sdk.models import SDKSession, SDKTranscriptTurn
from sdk.providers.zoom_rtms.control import ZoomRTMSControlClient
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

    def start_zoom_rtms(
        self,
        *,
        session: SDKSession,
        participant_user_id: str | None = None,
    ) -> dict:
        if not session.meeting_id:
            raise ValueError("Session does not have a Zoom meeting_id.")
        self.repository.update_session_status(session, "rtms_start_pending")
        result = ZoomRTMSControlClient(self.repository.db).start(
            meeting_id=session.meeting_id,
            participant_user_id=participant_user_id,
        )
        self.repository.update_session_status(session, "rtms_start_requested")
        return result
