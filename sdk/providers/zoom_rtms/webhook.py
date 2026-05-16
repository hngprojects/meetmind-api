from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from sdk.config import get_sdk_settings
from sdk.providers.zoom_rtms.events import (
    STARTED_EVENTS,
    STOPPED_EVENTS,
    URL_VALIDATION_EVENT,
    event_id,
    event_type,
    normalize_event_name,
    payload_object,
    rtms_stream_id,
)
from sdk.providers.zoom_rtms.manager import zoom_rtms_manager
from sdk.providers.zoom_rtms.webhook_security import zoom_url_validation_response
from sdk.repositories import SDKRepository


def handle_zoom_webhook(*, db: Session, payload: dict[str, Any]) -> dict:
    settings = get_sdk_settings()
    raw_event = event_type(payload)

    if raw_event == URL_VALIDATION_EVENT:
        plain_token = payload_object(payload).get("plainToken") or payload_object(
            payload
        ).get("plain_token")
        return zoom_url_validation_response(
            str(plain_token), settings.zoom_webhook_secret_token
        )

    normalized = normalize_event_name(raw_event)
    repo = SDKRepository(db)
    repo.record_provider_event(
        provider="zoom",
        event_id=event_id(payload),
        event_type=normalized,
        session_id=None,
        provider_stream_id=rtms_stream_id(payload),
        payload=payload,
    )

    if raw_event in STARTED_EVENTS or normalized == "meeting.rtms_started":
        return zoom_rtms_manager.start_from_webhook(db=db, payload=payload)

    if raw_event in STOPPED_EVENTS or normalized == "meeting.rtms_stopped":
        return zoom_rtms_manager.stop_from_webhook(db=db, payload=payload)

    return {"received": True, "event": normalized}
