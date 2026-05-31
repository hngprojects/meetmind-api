"""Service health endpoints."""

from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import DBSession
from app.core.responses import success

router = APIRouter()


@router.get("")
async def health(db: DBSession):
    await db.execute(text("SELECT 1"))
    return success({"status": "ok"}, message="Service healthy")
