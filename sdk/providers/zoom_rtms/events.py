from __future__ import annotations

from typing import Any

STARTED_EVENTS = {
    "meeting.rtms_started",
    "meeting.rtms.started",
    "meeting.rtms.start",
}
STOPPED_EVENTS = {
    "meeting.rtms_stopped",
    "meeting.rtms.stopped",
    "meeting.rtms.stop",
}
URL_VALIDATION_EVENT = "endpoint.url_validation"


def event_type(payload: dict[str, Any]) -> str:
    return str(payload.get("event") or "")


def normalize_event_name(name: str) -> str:
    if name in STARTED_EVENTS:
        return "meeting.rtms_started"
    if name in STOPPED_EVENTS:
        return "meeting.rtms_stopped"
    return name


def payload_object(payload: dict[str, Any]) -> dict[str, Any]:
    obj = payload.get("payload") or payload
    return obj if isinstance(obj, dict) else {}


def event_id(payload: dict[str, Any]) -> str | None:
    value = payload.get("event_id") or payload.get("event_ts")
    return str(value) if value is not None else None


def meeting_id(payload: dict[str, Any]) -> str | None:
    obj = payload_object(payload)
    value = (
        obj.get("meeting_id")
        or obj.get("meetingId")
        or obj.get("meeting_number")
        or obj.get("meetingNumber")
        or obj.get("uuid")
    )
    return str(value) if value is not None else None


def rtms_stream_id(payload: dict[str, Any]) -> str | None:
    obj = payload_object(payload)
    value = obj.get("rtms_stream_id") or obj.get("rtmsStreamId") or obj.get("stream_id")
    return str(value) if value is not None else None


def rtms_join_payload(payload: dict[str, Any]) -> dict[str, Any]:
    obj = payload_object(payload)
    return obj
