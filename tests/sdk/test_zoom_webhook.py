import hashlib
import hmac
import json
import time

from sdk.providers.zoom_rtms.events import (
    meeting_id,
    normalize_event_name,
    rtms_stream_id,
)
from sdk.providers.zoom_rtms.webhook_security import (
    verify_zoom_signature,
    zoom_url_validation_response,
)


def test_url_validation_response_uses_zoom_secret_token():
    response = zoom_url_validation_response("plain-token", "secret-token")
    expected = hmac.new(
        b"secret-token",
        b"plain-token",
        hashlib.sha256,
    ).hexdigest()

    assert response == {"plainToken": "plain-token", "encryptedToken": expected}


def test_verify_zoom_signature_accepts_valid_signed_body():
    body = json.dumps({"event": "meeting.rtms_started"}).encode("utf-8")
    timestamp = str(int(time.time()))
    secret = "secret-token"
    signature = "v0=" + hmac.new(
        secret.encode("utf-8"),
        f"v0:{timestamp}:{body.decode('utf-8')}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    assert verify_zoom_signature(
        raw_body=body,
        timestamp=timestamp,
        signature=signature,
        secret_token=secret,
    )


def test_rtms_event_mapping_supports_zoom_payload_shapes():
    payload = {
        "event": "meeting.rtms.started",
        "payload": {
            "meeting_uuid": "abc",
            "meeting_id": "123",
            "rtms_stream_id": "stream-1",
            "server_urls": "wss://example.zoom.us",
            "signature": "signed",
        },
    }

    assert normalize_event_name(payload["event"]) == "meeting.rtms_started"
    assert meeting_id(payload) == "123"
    assert rtms_stream_id(payload) == "stream-1"
