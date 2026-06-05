from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import jwt
from jwt.exceptions import InvalidTokenError

from app.core.config import settings
from app.core.utils import utcnow

# Sentinel value stored in the ``type`` claim so the decoder can reject
# tokens that were signed for a different purpose (e.g. access tokens).
INTERVIEW_TOKEN_TYPE = "interview_access"


def create_interview_token(
    interview_id: uuid.UUID,
    scheduled_start: Any,  # datetime | None
    scheduled_end: Any,  # datetime | None
) -> str:
    """Issue a signed JWT that grants a candidate access to interview details.

    The token is valid from **30 minutes before** the interview's scheduled
    start until **30 minutes after** its scheduled end.

    Safety guarantees
    -----------------
    * If ``scheduled_start`` / ``scheduled_end`` are ``None`` (unscheduled
      interview), the token is issued immediately and expires in
      ``MIN_VALIDITY_HOURS``.
    * If the computed expiry is already in the past (e.g. a past interview),
      the expiry is extended to ``now + MIN_VALIDITY_HOURS`` so the link
      remains usable.
    * ``nbf`` is clamped to *at most* ``now`` so the token is always
      immediately usable when the email is sent.

    Args:
        interview_id: UUID of the interview.
        scheduled_start: Interview start time (UTC-aware datetime), or ``None``.
        scheduled_end: Interview end time (UTC-aware datetime), or ``None``.

    Returns:
        A compact, signed JWT string.
    """
    # Minimum window the token must remain valid after issuance, regardless
    # of the interview's schedule (covers unscheduled / past interviews).
    MIN_VALIDITY_HOURS = 24

    now = utcnow()

    # nbf: 30 min before scheduled start, but never in the future relative
    # to now so that the token is immediately usable when the email lands.
    if scheduled_start is not None:
        nbf = min(scheduled_start - timedelta(minutes=30), now)
    else:
        nbf = now

    # exp: 30 min after scheduled end, but at least MIN_VALIDITY_HOURS from
    # now so that links for past / unscheduled interviews are still valid.
    if scheduled_end is not None:
        exp = max(
            scheduled_end + timedelta(minutes=30),
            now + timedelta(hours=MIN_VALIDITY_HOURS),
        )
    else:
        exp = now + timedelta(hours=MIN_VALIDITY_HOURS)

    payload = {
        "sub": str(interview_id),
        "type": INTERVIEW_TOKEN_TYPE,
        "iat": now,
        "nbf": nbf,
        "exp": exp,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_interview_token(token: str) -> dict:
    """Decode and validate an interview JWT.

    Args:
        token: The encoded JWT string.

    Returns:
        The decoded claims dictionary.

    Raises:
        jwt.exceptions.ExpiredSignatureError: Token has expired.
        jwt.exceptions.InvalidTokenError: Token is malformed, signature is
            invalid, or the ``type`` claim does not match.
    """
    payload = jwt.decode(
        token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
    )
    if payload.get("type") != INTERVIEW_TOKEN_TYPE:
        raise InvalidTokenError("Token type mismatch for interview access")
    return payload
