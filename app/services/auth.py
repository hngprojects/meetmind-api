"""Authentication service: password hashing, user creation, JWT issuance."""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import status
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import UserAlreadyExistsException
from app.core.responses import APIError
from app.models.user import ActiveSession, PasswordResetToken, RefreshToken, User
from app.schemas.auth import SignupRequest
from app.services.email_service import send_password_reset_security_alert

# Pre-computed once at import time. Used to run a constant-time bcrypt check
# when no account matches the submitted email, preventing timing-based
# account enumeration (criteria 9 / 13 of AUTH-SI-02-BE).
_DUMMY_HASH: str = bcrypt.hashpw(b"__dummy__", bcrypt.gensalt()).decode()

RESET_TOKEN_EXPIRY_MINUTES = 60
logger = logging.getLogger(__name__)


def _now() -> datetime:
    """Return the current UTC timestamp as a timezone-aware datetime.

    Returns:
        The current time in UTC.
    """
    return datetime.now(timezone.utc)


def _hash_token(raw: str) -> str:
    """Compute a stable SHA-256 digest for a refresh-token string.

    Args:
        raw: The raw token string to hash.

    Returns:
        Hex-encoded SHA-256 digest suitable for database lookup.
    """
    return hashlib.sha256(raw.encode()).hexdigest()


def _generate_jti() -> str:
    """Return a cryptographically random JWT ID (``jti``) string.

    Returns:
        A URL-safe, base64-encoded random string of 16 bytes.
    """
    return secrets.token_urlsafe(16)


class AuthService:
    """Encapsulate authentication primitives used by the auth routes.

    All methods are coroutines so they compose cleanly with the async
    SQLAlchemy session and FastAPI request lifecycle.
    """

    @staticmethod
    async def hash_password(password: str) -> str:
        """Hash a plaintext password using bcrypt.

        Args:
            password: The plaintext password supplied by the user.

        Returns:
            The bcrypt-hashed password as a UTF-8 string.
        """
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

    @staticmethod
    async def verify_password(password: str, hashed: str) -> bool:
        """Verify a plaintext password against a bcrypt hash.

        Args:
            password: The plaintext password being checked.
            hashed: The previously stored bcrypt hash.

        Returns:
            ``True`` if the password matches the hash, otherwise ``False``.
        """
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))

    @staticmethod
    async def check_email_exists(email: str, db: AsyncSession) -> bool:
        """Check whether a user is already registered with the given email.

        Args:
            email: Email address to look up.
            db: Active async database session.

        Returns:
            ``True`` if a user row exists for ``email``, else ``False``.
        """
        result = await db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def create_user(request: SignupRequest, db: AsyncSession) -> User:
        """Create a new user row, after asserting the email is unused.

        Args:
            request: Validated signup payload.
            db: Active async database session.

        Returns:
            The newly created :class:`User`, flushed but not committed.

        Raises:
            UserAlreadyExistsException: If ``request.email`` is already
                registered to another account.
        """
        if await AuthService.check_email_exists(request.email, db):
            raise UserAlreadyExistsException(email=request.email)

        hashed_password = await AuthService.hash_password(request.password)
        user = User(
            name=request.name,
            email=request.email,
            password_hash=hashed_password,
        )
        if settings.MOCK_EMAILS:
            user.is_verified = True
        db.add(user)
        await db.flush()
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def create_access_token(user: User) -> str:
        """Issue a signed JWT access token for the given user.

        Args:
            user: The user the token should be issued for.

        Returns:
            The encoded JWT as a compact serialization string.
        """
        now = _now()
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        payload = {
            "sub": str(user.id),
            "name": user.name,
            "email": user.email,
            "exp": expire,
            "iat": now,
            "jti": _generate_jti(),
            "type": "access",
        }
        return jwt.encode(
            payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM
        )

    @staticmethod
    async def decode_access_token(token: str) -> dict:
        """Decode and validate a previously issued access token.

        Args:
            token: The encoded JWT string.

        Returns:
            The decoded JWT claims as a dictionary.

        Raises:
            jwt.exceptions.InvalidTokenError: If the token signature are invalid.
        """
        return jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )

    @staticmethod
    async def create_refresh_token(
        db: AsyncSession,
        user_id: uuid.UUID,
        ip_address: str | None = None,
        device_hint: str | None = None,
    ) -> tuple[str, datetime]:
        """Generate, persist, and return a new refresh token.

        Only the SHA-256 hash is stored in the database. Also creates an
        ``ActiveSession`` row to track the session for revocation and auditing.

        Args:
            db: Active async database session.
            user_id: Identifier of the user the token is issued for.
            ip_address: Client IP address for session auditing.
            device_hint: Optional client hint (e.g. user-agent prefix).

        Returns:
            A tuple of ``(raw_token, expires_at)``.
        """
        raw = secrets.token_urlsafe(48)
        token_hash = _hash_token(raw)
        now = _now()
        expires_at = now + timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES)

        db.add(
            RefreshToken(
                user_id=user_id,
                token_hash=token_hash,
                expires_at=expires_at,
            )
        )
        db.add(
            ActiveSession(
                user_id=user_id,
                refresh_token_hash=token_hash,
                ip_address=ip_address,
                device_hint=device_hint,
                last_seen_at=now,
            )
        )
        await db.commit()
        return raw, expires_at

    @staticmethod
    async def login(email: str, password: str, db: AsyncSession) -> User:
        """Authenticate a user by email and password.

        Always runs bcrypt regardless of whether the email exists, preventing
        timing-based account enumeration.

        Args:
            email: The user's email address.
            password: The plaintext password to verify.
            db: Active async database session.

        Returns:
            The authenticated :class:`User`.

        Raises:
            APIError: 401 if the email is not found or the password is wrong.
        """
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        # Always run bcrypt — even when the user doesn't exist — so the
        # response time is indistinguishable between wrong-email and wrong-password.
        stored_hash = (
            user.password_hash if (user and user.password_hash) else _DUMMY_HASH
        )
        password_ok = await AuthService.verify_password(password, stored_hash)

        if not user or not user.password_hash or not password_ok:
            raise APIError(
                "Invalid email or password",
                status_code=status.HTTP_401_UNAUTHORIZED,
                code="invalid_credentials",
            )

        return user

    @staticmethod
    async def create_password_reset_token(db: AsyncSession, user: User) -> str:
        """Generate, persist, and return a new password reset token.

        Invalidates all previously unused reset tokens for the user before
        creating a new one (criterion 9 of AUTH-FPW-05-BE).

        Args:
            db: Active async database session.
            user: The user requesting a password reset.

        Returns:
            The raw (un-hashed) reset token string to embed in the email link.
        """
        result = await db.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
            )
        )
        now = _now()
        for old in result.scalars().all():
            old.used_at = now

        raw = secrets.token_urlsafe(48)
        token_hash = _hash_token(raw)
        expires_at = now + timedelta(minutes=RESET_TOKEN_EXPIRY_MINUTES)

        rt = PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        db.add(rt)
        await db.commit()
        return raw

    @staticmethod
    async def reset_password(
        raw_token: str,
        new_password: str,
        db: AsyncSession,
        background_tasks=None,
    ) -> None:
        """Validate a password reset token and update the user's password.

        Token validation (exists, not used, not expired) and the password +
        token update are performed in a single commit so the account is never
        left in a partially updated state (criterion 10).

        All token validation failures raise the same generic error to prevent
        leaking which specific check failed (criterion 9).

        Args:
            raw_token: The raw reset token from the client.
            new_password: The new plaintext password (pre-validated by schema).
            db: Active async database session.

        Raises:
            APIError: 400 for any token validation failure (invalid, expired, used).
        """
        token_hash = _hash_token(raw_token)
        result = await db.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == token_hash
            )
        )
        rt = result.scalar_one_or_none()

        # Single generic error for all failure modes
        _invalid = APIError(
            "This reset link is invalid or has expired.",
            status_code=status.HTTP_400_BAD_REQUEST,
            code="invalid_reset_token",
        )

        if not rt:
            raise _invalid
        if rt.used_at:
            raise _invalid

        expires_at = rt.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < _now():
            raise _invalid

        result = await db.execute(select(User).where(User.id == rt.user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise _invalid

        # Write both changes in one commit — if the commit fails, both roll back
        user.password_hash = await AuthService.hash_password(new_password)
        rt.used_at = _now()

        # after a successful password reset, revoke every active session
        await db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user.id,
                RefreshToken.revoked.is_(False),
            )
            .values(revoked=True)
        )

        # Remove all active sessions for this user in a single statement
        await db.execute(delete(ActiveSession).where(ActiveSession.user_id == user.id))

        await db.commit()
        try:
            await send_password_reset_security_alert(
                user.email, user.name, background_tasks=background_tasks
            )
        except Exception:
            logger.exception(
                "Failed to send password reset security alert for user %s",
                user.id,
            )

    @staticmethod
    def get_next_step(user: User) -> str:
        """Return the frontend routing hint for the given user's account state.

        Args:
            user: The authenticated user.

        Returns:
            ``"verify_email"`` if the account is unverified,
            ``"onboarding"`` if the profile is incomplete,
            ``"dashboard"`` otherwise.
        """
        if not user.is_verified:
            return "verify_email"
        if not user.onboarding_completed:
            return "onboarding"
        return "dashboard"

    @staticmethod
    async def refresh_access_token(
        raw_token: str,
        db: AsyncSession,
        ip_address: str | None = None,
    ) -> dict:
        """Rotate a refresh token and issue a new access token.

        The old refresh token is revoked and a new one is issued in a single
        commit (rotation). The associated ``ActiveSession`` is updated with
        the new token hash and ``last_seen_at``.

        Args:
            raw_token: The raw refresh token string from the client.
            db: Active async database session.
            ip_address: Client IP, used to update the session record.

        Returns:
            A dict with ``access_token``, ``refresh_token``,
            ``access_expires_at``, ``refresh_expires_at``, and ``user``.

        Raises:
            APIError: 401 for any token validation failure (not found, revoked,
                expired, or orphaned user) — single generic error prevents
                enumeration of which check failed.
        """
        token_hash = _hash_token(raw_token)
        result = await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        rt = result.scalar_one_or_none()

        _unauthorized = APIError(
            "Invalid or expired refresh token",
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="unauthorized",
        )

        expires_at = rt.expires_at if rt else None
        if expires_at and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if not rt or rt.revoked or not expires_at or expires_at < _now():
            raise _unauthorized

        result = await db.execute(select(User).where(User.id == rt.user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise _unauthorized

        # Rotate: new refresh token replaces the old one
        new_raw = secrets.token_urlsafe(48)
        new_hash = _hash_token(new_raw)
        now = _now()
        new_expires_at = now + timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES)

        db.add(
            RefreshToken(
                user_id=rt.user_id, token_hash=new_hash, expires_at=new_expires_at
            )
        )
        rt.revoked = True

        # Update the active session to track the new token
        session_result = await db.execute(
            select(ActiveSession).where(ActiveSession.refresh_token_hash == token_hash)
        )
        active_session = session_result.scalar_one_or_none()
        if active_session:
            active_session.refresh_token_hash = new_hash
            active_session.last_seen_at = now
            if ip_address:
                active_session.ip_address = ip_address
        else:
            db.add(
                ActiveSession(
                    user_id=rt.user_id,
                    refresh_token_hash=new_hash,
                    ip_address=ip_address,
                    last_seen_at=now,
                )
            )

        await db.commit()

        access_token = await AuthService.create_access_token(user)
        expiry_minutes = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_expires_at = now + expiry_minutes

        return {
            "access_token": access_token,
            "refresh_token": new_raw,
            "access_expires_at": access_expires_at,
            "refresh_expires_at": new_expires_at,
            "user": user,
        }

    @staticmethod
    async def logout(raw_token: str, db: AsyncSession) -> None:
        """Revoke a refresh token and remove the active session.

        Args:
            raw_token: The raw refresh token string from the client.
            db: Active async database session.

        Raises:
            APIError: 401 if the token is not found.
        """
        token_hash = _hash_token(raw_token)
        result = await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        rt = result.scalar_one_or_none()

        if not rt:
            raise APIError(
                "Invalid refresh token",
                status_code=status.HTTP_401_UNAUTHORIZED,
                code="invalid_refresh_token",
            )

        rt.revoked = True

        session_result = await db.execute(
            select(ActiveSession).where(ActiveSession.refresh_token_hash == token_hash)
        )
        active_session = session_result.scalar_one_or_none()
        if active_session:
            await db.delete(active_session)

        await db.commit()

    @staticmethod
    async def blacklist_access_token_raw(token: str) -> None:
        """Blacklist an access token by its raw JWT string.

        Decodes the ``jti`` and ``exp`` claims and stores the ``jti`` in
        Redis with a TTL equal to the remaining token lifetime.

        Args:
            token: The raw JWT access token string.
        """
        from app.core.redis import blacklist_token

        try:
            payload = jwt.decode(
                token,
                settings.JWT_SECRET,
                algorithms=[settings.JWT_ALGORITHM],
                options={"verify_exp": False},
            )
            jti = payload.get("jti")
            exp = payload.get("exp")
            if not jti or not exp:
                return
            remaining = int(exp) - int(_now().timestamp())
            await blacklist_token(jti, remaining)
        except Exception:
            logger.debug("Could not blacklist access token on logout")
