import bcrypt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException

from app.models.user import User
from app.schemas.auth import SignupRequest


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
            raise HTTPException(status_code=400, detail="Email already registered")

        # Hash password
        hashed_password = await AuthService.hash_password(request.password)

        # Create user
        user = User(
            name=request.name,
            email=request.email,
            password_hash=hashed_password
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user