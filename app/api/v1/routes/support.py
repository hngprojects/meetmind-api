from fastapi import APIRouter, status

from app.api.deps import DBSession
from app.core.responses import success
from app.schemas.support import ContactSupportRequest
from app.services.support import SupportService

router = APIRouter()


@router.post("/contact", status_code=status.HTTP_201_CREATED)
async def contact_support(
    payload: ContactSupportRequest,
    db: DBSession,
):
    ticket = await SupportService.create_ticket(payload, db)

    return success(
        ticket.model_dump(mode="json"),
        message="Support request submitted successfully",
        status_code=status.HTTP_201_CREATED,
    )
