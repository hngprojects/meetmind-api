"""Google OAuth 2.0 service: authorization URL, token exchange, user info."""

from __future__ import annotations

import urllib.parse

import httpx
from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.responses import APIError
from app.models.user import SSOProvider, User

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

_SCOPES = "openid email profile"


def build_authorization_url(state: str) -> str:
    """Return the Google OAuth consent screen URL to redirect the user to.

    Args:
        state: A random per-request token embedded in the URL and mirrored
            back by Google. Verified in the callback to prevent CSRF.

    Returns:
        A fully-formed, URL-encoded URL string with all required OAuth parameters.
    """
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": _SCOPES,
        "access_type": "offline",
        "prompt": "select_account",
        "state": state,
    }
    return f"{_GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"


async def exchange_code(code: str) -> dict:
    """Exchange an authorization code for Google OAuth tokens.

    Args:
        code: The authorization code returned by Google in the callback.

    Returns:
        The token response dict from Google (contains ``access_token`` etc.).

    Raises:
        APIError: 401 if Google rejects or cannot validate the code.
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            _GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )

    if response.status_code != 200:
        raise APIError(
            "Invalid or expired Google authorization code",
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="google_auth_error",
        )

    data = response.json()
    if not data.get("access_token"):
        raise APIError(
            "Google did not return a valid access token",
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="google_auth_error",
        )

    return data


async def get_google_user(access_token: str) -> dict:
    """Fetch the authenticated user's profile from Google.

    Args:
        access_token: A valid Google OAuth access token.

    Returns:
        The user info dict from Google (``id``, ``email``, ``name``, etc.).

    Raises:
        APIError: 401 if the token is invalid or expired.
        APIError: 401 if Google returns incomplete identity data.
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            _GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )

    if response.status_code != 200:
        raise APIError(
            "Invalid or expired Google access token",
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="google_auth_error",
        )

    data = response.json()

    if not data.get("id") or not data.get("email"):
        raise APIError(
            "Incomplete identity data returned by Google",
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="google_auth_error",
        )

    return data


async def find_or_create_user(google_user: dict, db: AsyncSession) -> User:
    """Resolve a Google profile to a local user, creating one if needed.

    Flow:
    1. If ``sso_providers`` already links this Google ID → return that user.
    2. If ``users.email`` matches but no SSO link exists → raise 409 (conflict).
    3. Otherwise → create a new verified user and SSO provider row.

    Args:
        google_user: Validated user info dict from :func:`get_google_user`.
        db: Active async database session.

    Returns:
        The resolved or newly created :class:`User`.

    Raises:
        APIError: 409 if the email belongs to an existing password-based account.
    """
    google_id: str = google_user["id"]
    email: str = google_user["email"]

    # 1. Existing SSO link — returning OAuth user
    result = await db.execute(
        select(SSOProvider).where(
            SSOProvider.provider == "google",
            SSOProvider.provider_id == google_id,
        )
    )
    sso = result.scalar_one_or_none()
    if sso:
        result = await db.execute(select(User).where(User.id == sso.user_id))
        return result.scalar_one()

    # 2. Email collision with a password-based account — do NOT silently link
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    error_message = "An account with this email already exists. Please sign in."
    if user:
        raise APIError(
            error_message,
            status_code=status.HTTP_409_CONFLICT,
            code="email_conflict",
        )

    # 3. Brand-new user — create user row + SSO provider row
    user = User(
        name=google_user.get("name"),
        email=email,
        avatar_url=google_user.get("picture"),
        is_verified=True,
    )
    db.add(user)
    await db.flush()

    sso = SSOProvider(
        user_id=user.id,
        provider="google",
        provider_id=google_id,
    )
    db.add(sso)
    await db.commit()
    await db.refresh(user)

    return user
