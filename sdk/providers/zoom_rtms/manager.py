from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from sqlalchemy.orm import Session

from sdk.config import get_sdk_settings
from sdk.db import SDKSessionLocal
from sdk.providers.zoom_rtms.events import meeting_id, rtms_join_payload, rtms_stream_id
from sdk.repositories import SDKRepository
from sdk.wake_words import detect_wake_word

logger = logging.getLogger(__name__)


class ZoomRTMSRuntimeError(RuntimeError):
    pass


class ZoomRTMSManager:
    """Owns active Zoom RTMS clients.

    This uses Zoom's real `rtms` package at runtime. The import is lazy so local
    development and tests on unsupported platforms are not blocked until a real
    stream is started.
    """

    def __init__(self):
        self.clients: dict[str, Any] = {}
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.webhook_executor = ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="zoom-rtms-webhook",
        )

    def queue_start_from_webhook(self, *, payload: dict[str, Any]) -> None:
        self.webhook_executor.submit(
            self._start_from_webhook_with_new_session,
            payload,
        )

    def _start_from_webhook_with_new_session(self, payload: dict[str, Any]) -> None:
        db = SDKSessionLocal()
        try:
            self.start_from_webhook(db=db, payload=payload)
        except Exception:
            logger.exception(
                "Failed to start Zoom RTMS stream from webhook "
                "(meeting_id=%s, rtms_stream_id=%s).",
                meeting_id(payload),
                rtms_stream_id(payload),
            )
        finally:
            db.close()

    def start_from_webhook(self, *, db: Session, payload: dict[str, Any]) -> dict:
        settings = get_sdk_settings()
        stream_id = rtms_stream_id(payload)
        if not stream_id:
            raise ZoomRTMSRuntimeError(
                "RTMS started payload did not include stream id."
            )

        repo = SDKRepository(db)
        session = repo.find_zoom_session(meeting_id(payload))
        if not session:
            session = repo.create_session(
                platform="zoom",
                meeting_id=meeting_id(payload),
                meeting_url=None,
                agent_name="MeetMind",
                context=None,
                wake_words=settings.zoom_default_wake_words,
            )

        repo.update_session_status(session, "listening", provider_session_id=stream_id)

        try:
            import rtms
        except ImportError as exc:
            raise ZoomRTMSRuntimeError(
                "Zoom RTMS package is not installed. Install `rtms` on "
                "linux-x64 or darwin-arm64."
            ) from exc

        client = rtms.Client(executor=self.executor)
        if settings.zoom_rtms_enable_audio and hasattr(rtms, "AudioParams"):
            client.setAudioParams(
                rtms.AudioParams(
                    content_type=rtms.AudioContentType["RAW_AUDIO"],
                    codec=rtms.AudioCodec["OPUS"],
                    sample_rate=rtms.AudioSampleRate["SR_16K"],
                    channel=rtms.AudioChannel["STEREO"],
                    data_opt=rtms.AudioDataOption["AUDIO_MIXED_STREAM"],
                    duration=20,
                    frame_size=640,
                )
            )
        self._attach_callbacks(
            client=client, session_id=session.id, stream_id=stream_id
        )
        join_payload = rtms_join_payload(payload)
        client.join(
            join_payload,
            client=settings.zoom_client_id,
            secret=settings.zoom_client_secret,
        )
        self.clients[stream_id] = client

        return {
            "session": session.to_dict(),
            "rtms_stream_id": stream_id,
            "joined": True,
        }

    def stop_from_webhook(self, *, db: Session, payload: dict[str, Any]) -> dict:
        stream_id = rtms_stream_id(payload)
        repo = SDKRepository(db)
        session = repo.find_zoom_session(meeting_id(payload))
        if session:
            repo.update_session_status(session, "ended", provider_session_id=stream_id)

        client = self.clients.pop(stream_id, None) if stream_id else None
        if client and hasattr(client, "leave"):
            client.leave()
        elif client and hasattr(client, "release"):
            client.release()

        return {
            "session_id": session.id if session else None,
            "rtms_stream_id": stream_id,
            "stopped": True,
        }

    def _attach_callbacks(self, *, client, session_id: str, stream_id: str) -> None:
        def on_transcript(data, timestamp=None, metadata=None):
            db = SDKSessionLocal()
            try:
                repo = SDKRepository(db)
                session = repo.get_session(session_id)
                if not session:
                    return
                content = decode_text(data)
                if not content:
                    return
                wake_word = detect_wake_word(content, session.wake_words)
                repo.add_transcript_turn(
                    session=session,
                    source="zoom_rtms",
                    role="human",
                    speaker_name=getattr(metadata, "userName", None)
                    or getattr(metadata, "user_name", None),
                    speaker_id=str(
                        getattr(metadata, "userId", "")
                        or getattr(metadata, "user_id", "")
                        or ""
                    )
                    or None,
                    content=content,
                    timestamp_ms=int(timestamp) if timestamp is not None else None,
                    provider_stream_id=stream_id,
                    trigger_reason=f"wake_word:{wake_word}" if wake_word else None,
                )
            finally:
                db.close()

        def on_audio(data, timestamp=None, metadata=None):
            db = SDKSessionLocal()
            try:
                repo = SDKRepository(db)
                session = repo.get_session(session_id)
                if not session:
                    return
                content = f"[audio_chunk bytes={len(data) if data is not None else 0}]"
                repo.add_transcript_turn(
                    session=session,
                    source="zoom_rtms_audio",
                    role="system",
                    speaker_name=getattr(metadata, "userName", None)
                    or getattr(metadata, "user_name", None),
                    speaker_id=str(
                        getattr(metadata, "userId", "")
                        or getattr(metadata, "user_id", "")
                        or ""
                    )
                    or None,
                    content=content,
                    timestamp_ms=int(timestamp) if timestamp is not None else None,
                    provider_stream_id=stream_id,
                )
            finally:
                db.close()

        if hasattr(client, "on_transcript_data"):
            client.on_transcript_data(on_transcript)
        elif hasattr(client, "onTranscriptData"):
            client.onTranscriptData(on_transcript)

        if hasattr(client, "on_audio_data"):
            client.on_audio_data(on_audio)
        elif hasattr(client, "onAudioData"):
            client.onAudioData(on_audio)


def decode_text(data) -> str:
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="ignore").strip()
    return str(data).strip()


zoom_rtms_manager = ZoomRTMSManager()
