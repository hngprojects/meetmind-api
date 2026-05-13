"""Tests for the dashboard service layer."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.schemas.dashboard import (
    DashboardLiveResponse,
    DashboardStatsResponse,
    LiveInterviewItem,
)

# ---------------------------------------------------------------------------
# Helpers (Unchanged)
# ---------------------------------------------------------------------------


def _mock_db() -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    db.execute.return_value = result
    return db


def _make_count_row(**kwargs) -> MagicMock:
    # ... (implementation unchanged)
    row = MagicMock()
    row.total = kwargs.get("total", 0)
    row.in_progress = kwargs.get("in_progress", 0)
    row.scheduled = kwargs.get("scheduled", 0)
    row.completed = kwargs.get("completed", 0)
    row.needs_attention = kwargs.get("needs_attention", 0)
    return row


def _make_interview_row(**kwargs) -> MagicMock:
    # ... (implementation unchanged)
    row = MagicMock()
    row.id = kwargs.get("interview_id", uuid.uuid4())
    row.role_title = kwargs.get("role_title", "Backend Engineer")
    row.scheduled_start = kwargs.get("scheduled_start", None)
    row.questions_asked = kwargs.get("questions_asked", 3)
    row.questions_total = kwargs.get("questions_total", 8)
    row.full_name = kwargs.get("full_name", "Amara Osei")
    return row


# ---------------------------------------------------------------------------
# get_live_counts (Unchanged)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_live_counts_happy_path():
    # ... (test unchanged)
    from app.services.dashboard import get_live_counts

    workspace_id = uuid.uuid4()
    db = _mock_db()
    row = _make_count_row(
        total=10, in_progress=2, scheduled=4, completed=3, needs_attention=1
    )
    db.execute.return_value.one.return_value = row
    result = await get_live_counts(workspace_id, db)
    assert isinstance(result, DashboardLiveResponse)
    assert result.total == 10


@pytest.mark.asyncio
async def test_get_live_counts_empty_workspace():
    # ... (test unchanged)
    from app.services.dashboard import get_live_counts

    workspace_id = uuid.uuid4()
    db = _mock_db()
    db.execute.return_value.one.return_value = _make_count_row()
    result = await get_live_counts(workspace_id, db)
    assert result.total == 0


# ---------------------------------------------------------------------------
# get_live_interviews (MODIFIED)
# ---------------------------------------------------------------------------

# DELETE THE PATCH CONSTANTS AND HELPER
# _PATCH_INTERVIEW = "app.services.dashboard.Interview" (DELETED)
# _PATCH_CANDIDATE = "app.services.dashboard.Candidate" (DELETED)
# def _model_patches(): (DELETED)


def _db_returning(rows: list) -> AsyncMock:
    """Return a db mock whose execute().all() yields the given rows."""
    db = _mock_db()
    db.execute.return_value.all.return_value = rows
    return db


@pytest.mark.asyncio
async def test_get_live_interviews_happy_path():
    """In-progress interviews are returned with all fields populated."""
    from app.services.dashboard import get_live_interviews

    workspace_id = uuid.uuid4()
    started = datetime.now(UTC) - timedelta(minutes=25, seconds=42)
    row = _make_interview_row(scheduled_start=started)
    db = _db_returning([row])

    # REMOVED `with _model_patches():`
    result = await get_live_interviews(workspace_id, db)

    assert isinstance(result, DashboardStatsResponse)
    assert len(result.live_interviews) == 1
    item = result.live_interviews[0]
    assert isinstance(item, LiveInterviewItem)
    assert abs(item.elapsed_seconds - 1542) < 3


@pytest.mark.asyncio
async def test_get_live_interviews_null_scheduled_start():
    """When scheduled_start is null, elapsed_seconds must be None — not an error."""
    from app.services.dashboard import get_live_interviews

    workspace_id = uuid.uuid4()
    db = _db_returning([_make_interview_row(scheduled_start=None)])

    # REMOVED `with _model_patches():`
    result = await get_live_interviews(workspace_id, db)

    assert result.live_interviews[0].elapsed_seconds is None


@pytest.mark.asyncio
async def test_get_live_interviews_empty_workspace():
    """No in-progress interviews returns an empty list — not an error."""
    from app.services.dashboard import get_live_interviews

    workspace_id = uuid.uuid4()
    db = _db_returning([])

    # REMOVED `with _model_patches():`
    result = await get_live_interviews(workspace_id, db)

    assert result.live_interviews == []


@pytest.mark.asyncio
async def test_get_live_interviews_multiple_sessions():
    from app.services.dashboard import get_live_interviews

    workspace_id = uuid.uuid4()
    now = datetime.now(UTC)
    rows = [
        _make_interview_row(
            scheduled_start=now - timedelta(minutes=10), full_name="Ada Lovelace"
        ),
        _make_interview_row(
            scheduled_start=now - timedelta(minutes=5), full_name="Grace Hopper"
        ),
    ]
    db = _db_returning(rows)
    result = await get_live_interviews(workspace_id, db)
    assert len(result.live_interviews) == 2


@pytest.mark.asyncio
async def test_get_live_interviews_cross_workspace_isolation():
    from app.services.dashboard import get_live_interviews

    workspace_b = uuid.uuid4()
    db = _db_returning([])
    result = await get_live_interviews(workspace_b, db)
    db.execute.assert_called_once()
    assert result.live_interviews == []


@pytest.mark.asyncio
async def test_get_live_interviews_null_role_title():
    from app.services.dashboard import get_live_interviews

    workspace_id = uuid.uuid4()
    row = _make_interview_row(role_title=None, scheduled_start=datetime.now(UTC))
    db = _db_returning([row])
    result = await get_live_interviews(workspace_id, db)
    assert result.live_interviews[0].role_title is None
