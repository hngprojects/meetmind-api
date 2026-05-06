import os
from app.core.config import settings

os.environ.setdefault("DATABASE_URL", settings.TEST_DATABASE_URL)

import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.db.session import get_session


def mock_get_session():
    """Yield a mock DB session so no real database interactions are avoided during tests."""
    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    yield session


@pytest.fixture
async def client():
    app.dependency_overrides[get_session] = mock_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()