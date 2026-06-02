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
    await db.execute(text("SELECT 1"))
    return success({"status": "ok"}, message="Service healthy")
