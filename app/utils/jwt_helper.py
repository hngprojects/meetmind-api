import datetime
import uuid
from typing import Any, Dict

from jose import jwt, JWTError

from app.core.config import settings

# Constants
INTERVIEW_TOKEN_TYPE = "interview_access"

def _now_utc() -> datetime.datetime:
    return datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)

def _not_before(scheduled_start: datetime.datetime) -> datetime.datetime:
    """Calculate token "not before" (nbf) claim: 30 minutes before start."""
    return scheduled_start - datetime.timedelta(minutes=30)

def _expiry(scheduled_end: datetime.datetime) -> datetime.datetime:
    """Calculate token expiry (exp) claim: 30 minutes after end."""
    return scheduled_end + datetime.timedelta(minutes=30)

def create_interview_token(
    interview_id: uuid.UUID,
    scheduled_start: datetime.datetime,
    scheduled_end: datetime.datetime,
    extra_claims: Dict[str, Any] | None = None,
) -> str:
    """Create a JWT that allows a candidate to access interview details.

    The token is valid from 30 minutes before the interview's scheduled start
    until 30 minutes after its scheduled end.

    Args:
        interview_id: UUID of the interview.
        scheduled_start: Interview start time (UTC).
        scheduled_end: Interview end time (UTC).
        extra_claims: Optional additional claims to embed.

    Returns:
        A signed JWT string.
    """
    now = _now_utc()
    nbf = _not_before(scheduled_start)
    exp = _expiry(scheduled_end)
    payload: Dict[str, Any] = {
        "sub": str(interview_id),
        "type": INTERVIEW_TOKEN_TYPE,
        "iat": now,
        "nbf": nbf,
        "exp": exp,
    }
    if extra_claims:
        payload.update(extra_claims)
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return token

def decode_interview_token(token: str) -> Dict[str, Any]:
    """Decode and validate an interview JWT.

    Raises:
        JWTError: If token is invalid, expired, or type mismatch.
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:
        raise JWTError(f"Invalid interview token: {exc}")
    # Verify token type
    if payload.get("type") != INTERVIEW_TOKEN_TYPE:
        raise JWTError("Token type mismatch for interview access")
    return payload
