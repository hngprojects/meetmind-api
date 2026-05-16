from __future__ import annotations

import hashlib
import hmac
import time


def zoom_url_validation_response(plain_token: str, secret_token: str) -> dict:
    encrypted_token = hmac.new(
        secret_token.encode("utf-8"),
        plain_token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {"plainToken": plain_token, "encryptedToken": encrypted_token}


def verify_zoom_signature(
    *,
    raw_body: bytes,
    timestamp: str | None,
    signature: str | None,
    secret_token: str,
    tolerance_seconds: int = 300,
) -> bool:
    if not secret_token:
        return True
    if not timestamp or not signature:
        return False

    try:
        request_ts = int(timestamp)
    except ValueError:
        return False

    if abs(int(time.time()) - request_ts) > tolerance_seconds:
        return False

    message = f"v0:{timestamp}:{raw_body.decode('utf-8')}"
    expected = "v0=" + hmac.new(
        secret_token.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
