import asyncio
import uuid
from typing import Callable, Optional
from sdk.providers.google_meet_browser.session import GoogleMeetSession
from sdk.providers.google_meet_browser.audio import setup_audio_devices


class BotManager:
    """Singleton that manages all active bot sessions."""

    def __init__(self):
        self._sessions: dict[str, GoogleMeetSession] = {}
        self._session_tasks: dict[str, asyncio.Task] = {}
        self._session_cleanup: dict[str, Callable[[], None]] = {}
        self._audio_ready = False

    async def ensure_audio_ready(self):
        if not self._audio_ready:
            await setup_audio_devices()
            self._audio_ready = True

    async def join(
        self,
        meeting_url: str,
        bot_name: str,
        on_event,
        interview_id: Optional[str] = None,
        cleanup_callback: Optional[Callable[[], None]] = None,
    ) -> str:
        await self.ensure_audio_ready()

        session_id = str(uuid.uuid4())
        session = GoogleMeetSession(
            session_id=session_id,
            meeting_url=meeting_url,
            bot_name=bot_name,
            on_event=on_event,
            interview_id=interview_id,
        )
        self._sessions[session_id] = session
        if cleanup_callback is not None:
            self._session_cleanup[session_id] = cleanup_callback

        task = asyncio.create_task(session.run())
        self._session_tasks[session_id] = task
        task.add_done_callback(lambda _: self._cleanup_session(session_id))
        return session_id

    async def leave(self, session_id: str):
        session = self._sessions.get(session_id)
        if session:
            await session.stop()

    async def speak(self, session_id: str, text: str):
        session = self._sessions.get(session_id)
        if session:
            await session.speak(text)

    def get_session(self, session_id: str) -> Optional[GoogleMeetSession]:
        return self._sessions.get(session_id)

    def list_sessions(self) -> list[dict]:
        return [
            {
                "session_id": sid,
                "status": s.status,
                "meeting_url": s.meeting_url,
                "interview_id": s.interview_id,
            }
            for sid, s in self._sessions.items()
        ]

    def _cleanup_session(self, session_id: str):
        cleanup = self._session_cleanup.pop(session_id, None)
        if cleanup is not None:
            try:
                cleanup()
            except Exception:
                pass
        self._sessions.pop(session_id, None)
        self._session_tasks.pop(session_id, None)

    def list_sessions(self) -> list[dict]:
        return [
            {
                "session_id": sid,
                "status": s.status,
                "meeting_url": s.meeting_url,
                "interview_id": s.interview_id,
            }
            for sid, s in self._sessions.items()
        ]


# Singleton instance
bot_manager = BotManager()