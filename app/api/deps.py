"""Reusable FastAPI dependency aliases."""

import uuid
from typing import Annotated

from fastapi import Cookie, Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import APIError
from app.db.session import get_session
from app.models.user import User
from app.services.auth import AuthService

DBSession = Annotated[AsyncSession, Depends(get_session)]
"""Type alias for an injected request-scoped async database session."""

# auto_error=False so we handle missing tokens ourselves with a consistent 401
_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    db: DBSession,
    access_token: str | None = Cookie(default=None),
    bearer_creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> User:
    """Resolve the authenticated user from a JWT access token.

    Accepts the token from either the ``access_token`` httponly cookie
    (set by the auth routes) or a ``Authorization: Bearer <token>`` header
    (useful for API clients and testing).

    Args:
        db: Async database session.
        access_token: Token from the httponly cookie, if present.
        authorization: Raw ``Authorization`` header value, if present.

    Returns:
        The authenticated :class:`User` row.

    Raises:
        APIError: 401 if no token is provided, the token is invalid or
            expired, or the ``sub`` claim is missing.
        APIError: 404 if the token is valid but the user no longer exists.
    """
    token = _resolve_token(access_token, bearer_creds)

    try:
        payload = await AuthService.decode_access_token(token)
    except JWTError:
        raise APIError(
            "Invalid or expired token",
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="unauthorized",
        )

    raw_id: str | None = payload.get("sub")
    if not raw_id:
        raise APIError(
            "Invalid token",
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="unauthorized",
        )

    try:
        user_id = uuid.UUID(raw_id)
    except ValueError:
        raise APIError(
            "Invalid token",
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="unauthorized",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise APIError(
            "User not found",
            status_code=status.HTTP_404_NOT_FOUND,
            code="user_not_found",
        )

    return user


def _resolve_token(
    cookie_token: str | None,
    bearer_creds: HTTPAuthorizationCredentials | None,
) -> str:
    """Extract the raw JWT string from cookie or Bearer credentials.

    Cookie takes priority. Falls back to the ``Authorization: Bearer`` header
    parsed by :data:`_bearer` (registered as an OpenAPI security scheme so
    the Swagger UI shows the padlock on protected endpoints).

    Args:
        cookie_token: Value of the ``access_token`` cookie.
        bearer_creds: Parsed Bearer credentials from the Authorization header.

    Returns:
        The raw JWT string.

    Raises:
        APIError: 401 if neither source provides a token.
    """
    if cookie_token:
        return cookie_token

    if bearer_creds:
        return bearer_creds.credentials

    raise APIError(
        "Not authenticated",
        status_code=status.HTTP_401_UNAUTHORIZED,
        code="unauthorized",
    )


CurrentUser = Annotated[User, Depends(get_current_user)]
"""Type alias for an injected authenticated user.

Usage in a protected route::

    @router.get("/me")
    async def get_me(user: CurrentUser):
        return success({"id": str(user.id), "email": user.email})
"""
