import os
from app.core.config import settings

os.environ.setdefault("DATABASE_URL", settings.TEST_DATABASE_URL)

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"

from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.pool import StaticPool

from httpx import AsyncClient, ASGITransport

from app.main import app
from app.models.base import Base
from app.db.session import get_session


def mock_get_session():
    """Yield a mock DB session so no real database interactions are avoided during tests."""
    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    yield session


# Force test DB
TEST_DATABASE_URL = "sqlite+aiosqlite://"


#Use StaticPool
engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


#Create tables ONCE using SAME connection
@pytest.fixture(scope="session", autouse=True)
async def create_tables():
    from app.models import user, email_verification 
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest.fixture
async def db_session():
    async with TestingSessionLocal() as session:
        yield session


# Override dependency to use test DB
@pytest.fixture(autouse=True)
def override_get_session(db_session):
    async def _override():
        yield db_session

    app.dependency_overrides[get_session] = _override
    yield
    app.dependency_overrides.clear()


# HTTP client
@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as ac:
        yield ac
