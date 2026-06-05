"""Tests for interview export endpoints.

GET /api/v1/interviews/{id}/export/markdown
GET /api/v1/interviews/{id}/export/pdf

Slice 1: Markdown happy path
Slice 2: Markdown no summary → 404
Slice 3: PDF happy path
Slice 4: PDF size exceeds 5MB → 400
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.interview import Interview, InterviewSummary
from app.models.scorecard import (
    InterviewScorecard,
    ScorecardCategory,
    ScorecardQuestion,
    ScorecardScore,
    ScorecardSignal,
)
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.auth import AuthService

EXPORT_URL = "/api/v1/interviews/{id}/summary/export"


async def create_user_with_workspace(db: AsyncSession) -> tuple[User, Workspace]:
    user = User(
        name="Test Recruiter",
        email=f"recruiter-{uuid.uuid4()}@example.com",
        is_verified=True,
    )
    db.add(user)
    await db.flush()

    workspace = Workspace(name="Test Workspace", created_by=user.id)
    db.add(workspace)
    await db.flush()

    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
    await db.commit()
    return user, workspace


async def create_interview(
    db: AsyncSession, user: User, workspace: Workspace, status: str = "completed"
) -> Interview:
    interview = Interview(
        workspace_id=workspace.id,
        interviewer_id=user.id,
        role_title="Senior Backend Engineer",
        platform="livekit",
        status=status,
    )
    db.add(interview)
    await db.commit()
    await db.refresh(interview)
    return interview


async def create_summary(
    db: AsyncSession,
    interview: Interview,
    *,
    with_assessment: bool = True,
) -> InterviewSummary:
    assessment = None
    if with_assessment:
        assessment = json.dumps(
            {
                "observation": "Strong candidate with solid backend fundamentals.",
                "highlights": ["Clear communicator", "Solid Python knowledge"],
                "red_flags": ["Limited experience with distributed systems"],
            }
        )

    summary = InterviewSummary(
        interview_id=interview.id,
        job_description="Build high-scale async APIs using FastAPI and PostgreSQL.",
        status="completed",
        ai_assessment=assessment,
        key_skills="Python,FastAPI,PostgreSQL",
    )
    db.add(summary)
    await db.commit()
    await db.refresh(summary)
    return summary


async def create_scorecard(db: AsyncSession, interview: Interview) -> None:
    """Seed a scorecard with one category, score, question, and signal."""
    scorecard = InterviewScorecard(interview_id=interview.id)
    db.add(scorecard)
    await db.flush()

    category = ScorecardCategory(
        workspace_id=interview.workspace_id,
        name="Technical Depth",
        sort_order=0,
    )
    db.add(category)
    await db.flush()

    score = ScorecardScore(
        scorecard_id=scorecard.id,
        category_id=category.id,
        score_pct=75,
        completed=True,
    )
    db.add(score)
    await db.flush()

    db.add(
        ScorecardQuestion(
            score_id=score.id,
            content="Walk me through a system you built at scale.",
            sort_order=0,
        )
    )
    db.add(
        ScorecardSignal(
            score_id=score.id,
            label="Demonstrated systems thinking",
            sort_order=0,
        )
    )
    await db.commit()


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestMarkdownExport:
    @pytest.mark.anyio
    async def test_returns_200_with_markdown_content_type(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)
        interview = await create_interview(db_session, user, workspace)
        await create_summary(db_session, interview)

        response = await client.get(
            EXPORT_URL.format(id=interview.id),
            params={"format": "markdown"},
            headers=auth_header(token),
        )

        assert response.status_code == 200
        assert "text/markdown" in response.headers["content-type"]

    @pytest.mark.anyio
    async def test_response_is_file_attachment(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)
        interview = await create_interview(db_session, user, workspace)
        await create_summary(db_session, interview)

        response = await client.get(
            EXPORT_URL.format(id=interview.id),
            params={"format": "markdown"},
            headers=auth_header(token),
        )

        assert "attachment" in response.headers["content-disposition"]
        assert f"{interview.id}_report.md" in response.headers["content-disposition"]

    @pytest.mark.anyio
    async def test_markdown_contains_required_sections(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)
        interview = await create_interview(db_session, user, workspace)
        await create_summary(db_session, interview)

        response = await client.get(
            EXPORT_URL.format(id=interview.id),
            params={"format": "markdown"},
            headers=auth_header(token),
        )

        body = response.text
        assert "## Interview Overview" in body
        assert "## Job Description" in body
        assert "## Key Insights" in body
        assert "## Strengths" in body
        assert "## Areas of Concern" in body
        assert "## Scorecard" in body

    @pytest.mark.anyio
    async def test_markdown_contains_candidate_and_assessment_data(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)
        interview = await create_interview(db_session, user, workspace)
        await create_summary(db_session, interview)

        response = await client.get(
            EXPORT_URL.format(id=interview.id),
            params={"format": "markdown"},
            headers=auth_header(token),
        )

        body = response.text
        assert "Senior Backend Engineer" in body
        assert "Strong candidate with solid backend fundamentals." in body
        assert "Clear communicator" in body
        assert "Limited experience with distributed systems" in body

    @pytest.mark.anyio
    async def test_markdown_includes_scorecard_sections(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)
        interview = await create_interview(db_session, user, workspace)
        await create_summary(db_session, interview)
        await create_scorecard(db_session, interview)

        response = await client.get(
            EXPORT_URL.format(id=interview.id),
            params={"format": "markdown"},
            headers=auth_header(token),
        )

        body = response.text
        assert "Technical Depth" in body
        assert "75%" in body
        assert "Walk me through a system you built at scale." in body
        assert "Demonstrated systems thinking" in body

    @pytest.mark.anyio
    async def test_returns_404_when_no_summary_exists(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)
        interview = await create_interview(db_session, user, workspace)
        # No summary seeded

        response = await client.get(
            EXPORT_URL.format(id=interview.id),
            params={"format": "markdown"},
            headers=auth_header(token),
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "summary_not_ready"

    @pytest.mark.anyio
    async def test_returns_404_when_summary_has_no_assessment(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)
        interview = await create_interview(db_session, user, workspace)
        await create_summary(db_session, interview, with_assessment=False)

        response = await client.get(
            EXPORT_URL.format(id=interview.id),
            params={"format": "markdown"},
            headers=auth_header(token),
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "summary_not_ready"

    @pytest.mark.anyio
    async def test_returns_404_for_nonexistent_interview(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)

        response = await client.get(
            EXPORT_URL.format(id=uuid.uuid4()),
            params={"format": "markdown"},
            headers=auth_header(token),
        )

        assert response.status_code == 404

    @pytest.mark.anyio
    async def test_returns_404_for_another_users_interview(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_a, workspace_a = await create_user_with_workspace(db_session)
        user_b, _ = await create_user_with_workspace(db_session)
        token_b = await AuthService.create_access_token(user_b)
        interview = await create_interview(db_session, user_a, workspace_a)
        await create_summary(db_session, interview)

        response = await client.get(
            EXPORT_URL.format(id=interview.id),
            params={"format": "markdown"},
            headers=auth_header(token_b),
        )

        assert response.status_code == 404

    @pytest.mark.anyio
    async def test_returns_401_without_token(self, client: AsyncClient):
        response = await client.get(
            EXPORT_URL.format(
                id=uuid.uuid4(),
                params={"format": "markdown"},
            )
        )
        assert response.status_code == 401


# Check if WeasyPrint's system dependencies (GTK, GObject) are installed and importable
try:
    import weasyprint  # noqa: F401
    from weasyprint.text.ffi import pango  # noqa: F401

    weasyprint_available = True
except (ImportError, OSError):
    weasyprint_available = False


@pytest.mark.skipif(
    not weasyprint_available,
    reason="WeasyPrint system dependencies (GTK3/GObject) are not installed.",
)
class TestPdfExport:
    @pytest.mark.anyio
    async def test_returns_200_with_pdf_content_type(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)
        interview = await create_interview(db_session, user, workspace)
        await create_summary(db_session, interview)

        response = await client.get(
            EXPORT_URL.format(id=interview.id),
            params={"format": "pdf"},
            headers=auth_header(token),
        )

        assert response.status_code == 200
        assert "application/pdf" in response.headers["content-type"]

    @pytest.mark.anyio
    async def test_response_is_file_attachment(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)
        interview = await create_interview(db_session, user, workspace)
        await create_summary(db_session, interview)

        response = await client.get(
            EXPORT_URL.format(id=interview.id),
            params={"format": "pdf"},
            headers=auth_header(token),
        )

        assert "attachment" in response.headers["content-disposition"]
        assert f"{interview.id}_report.pdf" in response.headers["content-disposition"]

    @pytest.mark.anyio
    async def test_pdf_bytes_start_with_pdf_magic_bytes(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)
        interview = await create_interview(db_session, user, workspace)
        await create_summary(db_session, interview)

        response = await client.get(
            EXPORT_URL.format(id=interview.id),
            params={"format": "pdf"},
            headers=auth_header(token),
        )

        # All valid PDFs start with the %PDF magic bytes
        assert response.content[:4] == b"%PDF"

    @pytest.mark.anyio
    async def test_pdf_is_within_size_limit(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)
        interview = await create_interview(db_session, user, workspace)
        await create_summary(db_session, interview)

        response = await client.get(
            EXPORT_URL.format(id=interview.id),
            params={"format": "pdf"},
            headers=auth_header(token),
        )

        assert len(response.content) <= 5 * 1024 * 1024

    @pytest.mark.anyio
    async def test_pdf_returns_404_when_no_summary(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)
        interview = await create_interview(db_session, user, workspace)

        response = await client.get(
            EXPORT_URL.format(id=interview.id),
            params={"format": "pdf"},
            headers=auth_header(token),
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "summary_not_ready"

    @pytest.mark.anyio
    async def test_pdf_returns_404_for_another_users_interview(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_a, workspace_a = await create_user_with_workspace(db_session)
        user_b, _ = await create_user_with_workspace(db_session)
        token_b = await AuthService.create_access_token(user_b)
        interview = await create_interview(db_session, user_a, workspace_a)
        await create_summary(db_session, interview)

        response = await client.get(
            EXPORT_URL.format(id=interview.id),
            params={"format": "pdf"},
            headers=auth_header(token_b),
        )

        assert response.status_code == 404

    @pytest.mark.anyio
    async def test_pdf_returns_401_without_token(self, client: AsyncClient):
        response = await client.get(
            EXPORT_URL.format(
                id=uuid.uuid4(),
                params={"format": "pdf"},
            )
        )
        assert response.status_code == 401

    @pytest.mark.anyio
    async def test_returns_400_when_pdf_exceeds_5mb(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)
        interview = await create_interview(db_session, user, workspace)
        await create_summary(db_session, interview)

        # Patch weasyprint to return an oversized byte blob
        oversized = b"x" * (5 * 1024 * 1024 + 1)
        with patch("weasyprint.HTML") as mock_html:
            mock_html.return_value.write_pdf.return_value = oversized

            response = await client.get(
                EXPORT_URL.format(id=interview.id),
                params={"format": "pdf"},
                headers=auth_header(token),
            )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "export_too_large"
