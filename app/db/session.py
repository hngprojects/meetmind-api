"""Async SQLAlchemy engine and session factory."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

engine = create_async_engine(str(settings.DATABASE_URL), echo=False)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped async database session.

    Designed for use as a FastAPI dependency. The session is closed
    automatically when the request finishes.

    Yields:
        An :class:`sqlalchemy.ext.asyncio.AsyncSession` bound to the
        configured engine.
    """
    async with AsyncSessionLocal() as session:
        yield session
