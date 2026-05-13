from fastapi import APIRouter, status

from app.api.deps import DBSession
from app.core.responses import success
from app.schemas.subscription import SubscriptionRequest
from app.services.subscriptions import SubscriptionService

router = APIRouter()


@router.post(
    "/email",
    status_code=status.HTTP_201_CREATED,
)
async def subscribe_email(
    payload: SubscriptionRequest,
    db: DBSession,
):
    subscription = await SubscriptionService.subscribe(payload, db)

    return success(
        message="Email subscribed successfully",
        data={
            "id": str(subscription.id),
            "email": subscription.email,
        },
    )
