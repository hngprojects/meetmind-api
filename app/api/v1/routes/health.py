"""Service health endpoints."""

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from app.api.deps import DBSession
from app.core.responses import APIResponse, success

router = APIRouter()


class HealthData(BaseModel):
    status: str


@router.get("", response_model=APIResponse[HealthData])
async def health(db: DBSession):
    """Probe service liveness and database connectivity.

    Args:
        db: Async database session injected by FastAPI; a trivial
            ``SELECT 1`` is executed against it to confirm the connection
            is healthy.

    Returns:
        A standardized success envelope with ``data={"status": "ok"}``.
    """
    await db.execute(text("SELECT 1"))
    return success({"status": "ok"}, message="Service healthy")
