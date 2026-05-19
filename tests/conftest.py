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

# Delay importing `app` until after tests have disabled the rate limiter
from app.models.base import Base


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


def mock_get_session():
    """Yield a mock DB session so database interactions are avoided during tests."""
    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    yield session


# Force test DB
TEST_DATABASE_URL = "sqlite+aiosqlite://"

# Use StaticPool so all connections share the same in-memory database
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


# Create ALL tables once for the entire session
@pytest.fixture(scope="session", autouse=True)
async def create_tables():
    from app.models import (  # noqa: F401  # noqa: F401
        audit_log,
        email_verification,
        interview,
        user,
        workspace,
    )

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
    from app.main import app

    async def _override():
        yield db_session

    app.dependency_overrides[get_session] = _override
    yield
    app.dependency_overrides.clear()


# Disable rate limiting in tests by patching the limiter decorator to a no-op
@pytest.fixture(autouse=True)
def disable_rate_limiter():
    from app.core import limiter as limiter_mod

    # Make @limiter.limit(...) return the original function unmodified
    original_limit = limiter_mod.limiter.limit
    limiter_mod.limiter.limit = lambda *a, **k: lambda f: f
    try:
        yield
    finally:
        limiter_mod.limiter.limit = original_limit


# Prevent real Resend API calls in every test
@pytest.fixture(autouse=True)
def mock_send_verification_email():
    async def _noop(email, name, token):
        pass

    with patch("app.services.verification_service.send_verification_email", _noop):
        yield


# Stub Redis so tests don't need a running Redis server
@pytest.fixture(autouse=True)
def mock_redis():
    blacklisted: set[str] = set()

    async def _blacklist(jti, expires_in):
        if expires_in > 0:
            blacklisted.add(jti)

    async def _is_blacklisted(jti):
        return jti in blacklisted

    with (
        patch("app.core.redis.blacklist_token", side_effect=_blacklist),
        patch("app.core.redis.is_token_blacklisted", side_effect=_is_blacklisted),
        patch("app.core.middleware.is_token_blacklisted", side_effect=_is_blacklisted),
    ):
        yield blacklisted


# HTTP client
@pytest.fixture
async def client():
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as ac:
        yield ac
