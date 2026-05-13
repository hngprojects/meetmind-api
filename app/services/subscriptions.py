from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import APIError
from app.models.subscription import EmailSubscription
from app.schemas.subscription import SubscriptionRequest


class SubscriptionService:
    @staticmethod
    async def subscribe(
        payload: SubscriptionRequest,
        db: AsyncSession,
    ) -> EmailSubscription:
        existing = await db.scalar(
            select(EmailSubscription).where(EmailSubscription.email == payload.email)
        )

        if existing:
            raise APIError(
                message="Email already subscribed",
                status_code=409,
                code="email_already_subscribed",
            )

        subscription = EmailSubscription(
            email=payload.email,
        )

        db.add(subscription)

        await db.commit()
        await db.refresh(subscription)

        return subscription