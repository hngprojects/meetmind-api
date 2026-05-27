"""Email verification service: token issuance, validation, and resend flow."""

from __future__ import annotations

import hashlib
import inspect
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import BackgroundTasks, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import APIError
from app.models.email_verification import EmailVerificationToken
from app.models.user import User
from app.services.email_service import send_verification_email
from app.services.interview import _get_or_create_workspace

TOKEN_EXPIRY_MINUTES = 30


def _hash_token(token: str) -> str:
    """Return a stable SHA-256 hex digest for a verification token.

    Args:
        token: Raw token string as issued to the user.

    Returns:
        Hex-encoded SHA-256 digest suitable for database lookup.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def _generate_token() -> str:
    """Generate a new cryptographically random URL-safe token.

    Returns:
        A 32-byte URL-safe token string.
    """
    return secrets.token_urlsafe(32)


def _now() -> datetime:
    """Return the current UTC timestamp as a timezone-aware datetime.

    Returns:
        The current time in UTC.
    """
    return datetime.now(timezone.utc)


class VerificationService:
    """Coordinate email-verification token lifecycle for user accounts.

    Provides token creation, redemption, and resend operations. All failure
    modes raise :class:`app.core.responses.APIError` so the central exception
    handlers render a consistent error envelope to clients.
    """

    async def create_verification_token(
        self,
        db: AsyncSession,
        user: User,
        background_tasks: BackgroundTasks | None = None,
    ) -> str:
        """Issue, persist, and email a verification token to the user.

        Any previously unused tokens for the same user are invalidated before
        the new one is created, ensuring only one active token exists at a time.

        Args:
            db: Active async database session.
            user: The user to issue the token for.

        Returns:
            The raw (un-hashed) token string.

        Raises:
            Exception: If the email delivery service fails. Callers should
                surface this as a safe 500.
        """
        # Invalidate all outstanding unused tokens for this user (criterion 8).
        result = await db.execute(
            select(EmailVerificationToken).where(
                EmailVerificationToken.user_id == user.id,
                EmailVerificationToken.used_at.is_(None),
            )
        )
        now = _now()
        for old in result.scalars().all():
            old.used_at = now

        raw_token = _generate_token()
        token_hash = _hash_token(raw_token)
        expires_at = now + timedelta(minutes=TOKEN_EXPIRY_MINUTES)

        token = EmailVerificationToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        db.add(token)

        sig = inspect.signature(send_verification_email)
        if "background_tasks" in sig.parameters and background_tasks is not None:
            await send_verification_email(
                user.email, user.name, raw_token, background_tasks=background_tasks
            )
        else:
            await send_verification_email(user.email, user.name, raw_token)

        await db.commit()
        return raw_token


    async def verify_email(self, db: AsyncSession, token: str) -> User:
        """Redeem a verification token and mark the owning user as verified.

        Args:
            db: Active async database session.
            token: Raw verification token submitted by the client.

        Returns:
            The :class:`User` that has just been marked verified.

        Raises:
            APIError: If the token is unknown, already redeemed, expired, or
                its owning user no longer exists.
        """
        token_hash = _hash_token(token)
        result = await db.execute(
            select(EmailVerificationToken).where(
                EmailVerificationToken.token_hash == token_hash
            )
        )
        record = result.scalar_one_or_none()

        if not record:
            raise APIError(
                "Invalid verification token",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="invalid_verification_token",
            )
        if record.used_at:
            raise APIError(
                "Token already used",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="token_already_used",
            )
        if _make_aware(record.expires_at) < _now():
            raise APIError(
                "Verification link has expired. Request a new one.",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="verification_token_expired",
                details={"next_step": "resend_verification"},
            )

        record.used_at = _now()

        result = await db.execute(select(User).where(User.id == record.user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise APIError(
                "User not found",
                status_code=status.HTTP_404_NOT_FOUND,
                code="user_not_found",
            )

        user.is_verified = True
        await _get_or_create_workspace(db, user)
        await db.commit()
        return user

    async def resend_verification(
        self,
        db: AsyncSession,
        email: str,
        background_tasks: BackgroundTasks | None = None,
    ) -> None:
        """Issue a fresh verification token for an unverified user.

        Args:
            db: Active async database session.
            email: Email address of the account requesting a new token.

        Raises:
            APIError: If no user has the supplied email or the user is
                already verified.
        """
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if not user:
            raise APIError(
                "User not found",
                status_code=status.HTTP_404_NOT_FOUND,
                code="user_not_found",
            )
        if user.is_verified:
            raise APIError(
                "User already verified",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="user_already_verified",
            )

        await self.create_verification_token(
            db, user, background_tasks=background_tasks
        )


def _make_aware(value: datetime) -> datetime:
    """Coerce a possibly naive datetime to a timezone-aware UTC datetime.

    SQLite (used in tests) round-trips ``DateTime`` columns as naive values,
    while Postgres preserves tzinfo. Normalize so comparisons are safe.

    Args:
        value: A naive or timezone-aware datetime.

    Returns:
        The same instant expressed in UTC with ``tzinfo`` set.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
