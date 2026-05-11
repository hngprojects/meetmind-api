"""Tests for the JWT blacklist (Redis) integration."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from jose import jwt

from app.core.config import settings
from app.models.user import ActiveSession, RefreshToken, User
from app.schemas.auth import SignupRequest
from app.services.auth import AuthService


async def _create_test_user(db_session, email: str) -> tuple[User, str]:
    """Create a test user and return the user + access token."""
    user = await AuthService.create_user(
        SignupRequest(name="Test User", email=email, password="Abcdefg1"),
        db_session,
    )
    await db_session.commit()
    access_token = await AuthService.create_access_token(user)
    return user, access_token


@pytest.mark.anyio
async def test_logout_blacklists_access_token(client, db_session, mock_redis):
    """Logging out should add the access token JTI to the blacklist."""
    user, access_token = await _create_test_user(db_session, "bl@test.com")

    _, refresh_expires_at = await AuthService.create_refresh_token(
        db_session, user.id
    )

    # We need the raw token — create it directly
    raw_refresh = secrets.token_urlsafe(48)

    token_hash = hashlib.sha256(raw_refresh.encode()).hexdigest()
    db_session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=datetime.now(timezone.utc)
            + timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES),
        )
    )
    db_session.add(
        ActiveSession(
            user_id=user.id,
            refresh_token_hash=token_hash,
            last_seen_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()

    claims = jwt.decode(
        access_token,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
        options={"verify_exp": False},
    )
    jti = claims["jti"]

    # Patch the lazy import inside blacklist_access_token_raw
    with patch(
        "app.core.redis.blacklist_token", new_callable=AsyncMock
    ) as mock_bl:
        resp = await client.post(
            "/api/v1/auth/logout",
            json={
                "access_token": access_token,
                "refresh_token": raw_refresh,
            },
        )
        assert resp.status_code == 200
        mock_bl.assert_awaited_once()
        called_jti = mock_bl.call_args[0][0]
        assert called_jti == jti


@pytest.mark.anyio
async def test_blacklisted_token_rejected_by_middleware(client, db_session, mock_redis):
    """A request with a blacklisted token should receive a 401."""
    _, access_token = await _create_test_user(db_session, "mw@test.com")

    claims = jwt.decode(
        access_token,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
        options={"verify_exp": False},
    )
    jti = claims["jti"]

    # Add JTI to the mock blacklist set
    mock_redis.add(jti)

    resp = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert resp.status_code == 401
    assert resp.json()["message"] == "Token has been revoked"


@pytest.mark.anyio
async def test_non_blacklisted_token_passes_middleware(client, db_session, mock_redis):
    """A valid, non-blacklisted token should reach the route handler."""
    _, access_token = await _create_test_user(db_session, "pass@test.com")

    resp = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["email"] == "pass@test.com"
