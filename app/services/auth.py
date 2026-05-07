"""Authentication service: password hashing, user creation, JWT issuance."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import UserAlreadyExistsException
from app.models.user import RefreshToken, User
from app.schemas.auth import SignupRequest


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
        db.add(user)
        await db.flush()
        return user

    @staticmethod
    async def create_access_token(user: User) -> str:
        """Issue a signed JWT access token for the given user.

        Args:
            user: The user the token should be issued for.

        Returns:
            The encoded JWT as a compact serialization string.
        """
        expire = _now() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        payload = {
            "sub": str(user.id),
            "name": user.name,
            "email": user.email,
            "exp": expire,
            "iat": _now(),
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
            jose.JWTError: If the token signature or claims are invalid.
        """
        return jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )

    @staticmethod
    async def create_refresh_token(db: AsyncSession, user_id: uuid.UUID) -> str:
        """Generate, persist, and return a new refresh token.

        Only the SHA-256 hash of the token is stored in the database; the
        raw value is returned to the caller for delivery to the client.

        Args:
            db: Active async database session.
            user_id: Identifier of the user the token is issued for.

        Returns:
            The raw URL-safe refresh-token string.
        """
        raw = secrets.token_urlsafe(48)
        token_hash = _hash_token(raw)
        expires_at = _now() + timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES)

        rt = RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        db.add(rt)
        await db.commit()
        await db.refresh(rt)
        return raw
