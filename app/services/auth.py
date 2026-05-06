import uuid
import hashlib
import secrets
import bcrypt
from datetime import datetime, timedelta, timezone

from jose import jwt
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import UserAlreadyExistsException
from app.models.user import User, RefreshToken
from app.schemas.auth import SignupRequest

def _now() -> datetime:
	return datetime.now(timezone.utc)

def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()

class AuthService:
    @staticmethod
    async def hash_password(password: str) -> str:
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

    @staticmethod
    async def verify_password(password: str, hashed: str) -> bool:
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

    @staticmethod
    async def check_email_exists(email: str, db: AsyncSession) -> bool:
        result = await db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def create_user(request: SignupRequest, db: AsyncSession) -> User:
        # Check if email exists
        if await AuthService.check_email_exists(request.email, db):
            raise UserAlreadyExistsException(email=request.email)

        # Hash password
        hashed_password = await AuthService.hash_password(request.password)

        # Create user
        user = User(
            name=request.name,
            email=request.email,
            password_hash=hashed_password
        )
        db.add(user)
        await db.flush()
        return user
    
    @staticmethod
    async def create_access_token(user: User) -> str:
        expire = _now() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        payload = {
            "sub": str(user.id),
            "name": user.name,
            "email": user.email,
            "exp": expire,
            "iat": _now(),
            "type": "access",
        }
        return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    
    @staticmethod
    async def decode_access_token(token: str) -> dict:
        """Raises JWTError if invalid or expired."""
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])

    @staticmethod
    async def create_refresh_token(db: AsyncSession, user_id: uuid.UUID) -> str:
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
