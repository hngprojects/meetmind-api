import logging

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import APIError
from app.models.integration import WaitlistSignup

logger = logging.getLogger(__name__)


class WaitlistService:
    @staticmethod
    async def signup(email: str, db: AsyncSession) -> WaitlistSignup:
        normalised = email.strip().lower()

        existing = await db.execute(
            select(WaitlistSignup).where(WaitlistSignup.email == normalised)
        )
        if existing.scalar_one_or_none() is not None:
            raise APIError(
                "This email address is already on the waitlist.",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="email_already_registered",
            )

        signup = WaitlistSignup(
            email=normalised,
            provider="email",
        )
        db.add(signup)
        await db.commit()
        await db.refresh(signup)

        logger.info("New waitlist signup: %s", normalised)
        return signup
