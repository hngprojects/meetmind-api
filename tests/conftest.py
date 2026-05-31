import sys
from unittest.mock import AsyncMock, MagicMock, patch
from app.schemas.interview import (
    InterviewPlanOutput,
    InterviewQuestionSchema,
    RubricCriterion,
)

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

# Stub heavy external modules before any app import to avoid
# ModuleNotFoundError from transitive dependencies not related to tests.
_FAKE_MODULES = [
    "openai",
]
for _mod in _FAKE_MODULES:
    sys.modules.setdefault(_mod, MagicMock())

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
        document,
        email_verification,
        interview,
        scorecard,
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
    async def _noop_verification(email, name, token, background_tasks=None):
        pass

    async def _noop_welcome(email, name, action_url=None, background_tasks=None):
        pass

    with (
        patch(
            "app.services.verification_service.send_verification_email",
            _noop_verification,
        ),
        patch("app.services.verification_service.send_welcome_email", _noop_welcome),
    ):
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


@pytest.fixture(autouse=True)
def mock_ai_generation():
    """
    Global mock for all AI-related service calls.
    Prevents 503 errors and saves API costs during testing.
    """
    fake_plan = InterviewPlanOutput(
        intro="Welcome to the mock interview.",
        questions=[
            InterviewQuestionSchema(
                text="Mock Question?", followUpHint="Hint", maxFollowUps=2
            )
        ],
        rubric=[
            # Add all three standard test criteria here
            RubricCriterion(name="Communication", description="Clear speech", weight=1),
            RubricCriterion(name="API Design", description="Design skills", weight=1),
            RubricCriterion(
                name="Problem Solving", description="Solving skills", weight=1
            ),
        ],
        closing="Thank you.",
    )

    with patch(
        "app.services.interview.InterviewService.generate_interview_plan",
        new=AsyncMock(return_value=fake_plan),
    ) as mock_plan:
        with patch(
            "app.services.ai_generation_service.generate_text",
            new=AsyncMock(return_value="Mocked AI Response"),
        ) as mock_text:
            yield (mock_plan, mock_text)


@pytest.fixture(autouse=True)
def mock_ai_planner():
    with patch(
        "app.services.ai_generation_service.AIGenerationService.generate_interview_plan"
    ) as mock:
        mock.return_value = InterviewPlanOutput(
            intro="Hello, welcome.",
            questions=[
                {"text": "Question 1", "followUpHint": "Hint", "maxFollowUps": 2}
            ],
            rubric=[{"name": "Skill 1", "description": "Desc", "weight": 3}],
            closing="Goodbye.",
        )
        yield mock

@pytest.fixture(autouse=True, scope="session")
def disable_otel():
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    trace.set_tracer_provider(TracerProvider())