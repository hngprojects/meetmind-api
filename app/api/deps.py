"""Reusable FastAPI dependency aliases."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session

DBSession = Annotated[AsyncSession, Depends(get_session)]
"""Type alias for an injected request-scoped async database session."""
