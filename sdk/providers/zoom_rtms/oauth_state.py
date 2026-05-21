from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time


class ZoomOAuthStateError(RuntimeError):
    pass


def create_oauth_state(secret: str, *, ttl_seconds: int = 600) -> str:
    if not secret:
        raise ZoomOAuthStateError("Zoom OAuth state secret is not configured.")
    payload = {
        "nonce": secrets.token_urlsafe(24),
        "iat": int(time.time()),
        "ttl": ttl_seconds,
    }
    encoded_payload = _base64url_encode(json.dumps(payload).encode("utf-8"))
    signature = _sign(encoded_payload, secret)
    return f"{encoded_payload}.{signature}"


def validate_oauth_state(state: str | None, secret: str) -> None:
    if not secret:
        raise ZoomOAuthStateError("Zoom OAuth state secret is not configured.")
    if not state or "." not in state:
        raise ZoomOAuthStateError("Invalid Zoom OAuth state.")
    encoded_payload, signature = state.rsplit(".", 1)
    expected = _sign(encoded_payload, secret)
    if not hmac.compare_digest(expected, signature):
        raise ZoomOAuthStateError("Invalid Zoom OAuth state signature.")

    try:
        payload = json.loads(_base64url_decode(encoded_payload))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ZoomOAuthStateError("Invalid Zoom OAuth state payload.") from exc

    issued_at = int(payload.get("iat") or 0)
    ttl = int(payload.get("ttl") or 0)
    if not issued_at or not ttl or issued_at + ttl < int(time.time()):
        raise ZoomOAuthStateError("Zoom OAuth state has expired.")


def _sign(value: str, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("utf-8").rstrip("=")


def _base64url_decode(value: str) -> str:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")
