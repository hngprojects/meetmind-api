import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.user import User
from app.models.email_verification import EmailVerificationToken


TOKEN_EXPIRY_MINUTES = 30


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _generate_token() -> str:
    return secrets.token_urlsafe(32)


class VerificationService:

    async def create_verification_token(self, db: AsyncSession, user_id):
        raw_token = _generate_token()
        token_hash = _hash_token(raw_token)

        expires_at = datetime.utcnow() + timedelta(minutes=TOKEN_EXPIRY_MINUTES)

        token = EmailVerificationToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )

        db.add(token)
        await db.commit()

        # simulate email sending
        print(f"[EMAIL VERIFICATION LINK]: /api/v1/auth/verify-email?token={raw_token}")

        return raw_token

    async def verify_email(self, db: AsyncSession, token: str):
        token_hash = _hash_token(token)

        result = await db.execute(
            select(EmailVerificationToken).where(
                EmailVerificationToken.token_hash == token_hash
            )
        )
        record = result.scalar_one_or_none()

        if not record:
            return None, "Invalid verification token"

        if record.used_at:
            return None, "Token already used"

        if record.expires_at < datetime.utcnow():
            return None, "Verification link expired"

        # mark token used
        record.used_at = datetime.utcnow()

        # mark user verified
        result = await db.execute(
            select(User).where(User.id == record.user_id)
        )
        user = result.scalar_one()

        user.is_verified = True

        await db.commit()

        return user, None

    async def resend_verification(self, db: AsyncSession, email: str):
        result = await db.execute(
            select(User).where(User.email == email)
        )
        user = result.scalar_one_or_none()

        if not user:
            return None, "User not found"

        if user.is_verified:
            return None, "User already verified"

        await self.create_verification_token(db, user.id)

        return True, None