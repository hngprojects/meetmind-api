from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.db.session import get_session
from app.main import app
from app.models.base import Base


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


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
    from app.models import email_verification, user  # noqa: F401
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


# Prevent real Resend API calls in every test
@pytest.fixture(autouse=True)
def mock_send_verification_email():
    async def _noop(email, name, token):
        pass

    with patch("app.services.verification_service.send_verification_email", _noop):
        yield


# HTTP client
@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as ac:
        yield ac
