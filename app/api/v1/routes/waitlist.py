import logging

from fastapi import APIRouter, status

from app.api.deps import DBSession
from app.core.responses import success
from app.schemas.waitlist import WaitlistRequest, WaitlistResponse
from app.services.waitlist import WaitlistService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
    summary="Join the public waitlist",
    description=(
        "Submit an email address to join the MeetMind waitlist. "
        "No authentication required. "
        "Returns 400 if the email is already registered."
    ),
)
async def join_waitlist(
    payload: WaitlistRequest,
    db: DBSession,
) -> None:
    signup = await WaitlistService.signup(
        email=payload.email,
        db=db,
    )

    return success(
        data=WaitlistResponse(
            email=signup.email,
            message="You are on the list. We will be in touch soon.",
        ).model_dump(),
        message="Successfully joined the waitlist",
        status_code=status.HTTP_201_CREATED,
    )
