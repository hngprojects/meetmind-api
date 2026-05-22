"""Tests for AIGenerationService."""

from __future__ import annotations

import sys
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Stub heavy document-processing modules that the service chain imports but
# tests never actually call. Remove these once pdfplumber etc. are installed.
for _mod in ("pdfplumber", "docx", "langchain_text_splitters"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

from app.core.responses import APIError
from app.models.interview import (
    Candidate,
    Interview,
    InterviewSummary,
    InterviewTranscript,
    InterviewTranscriptTurn,
)
from app.models.user import User
from app.models.workspace import Workspace
from app.services.ai_generation_service import AIGenerationService


# ── helpers ──────────────────────────────────────────────────────────


async def create_user(db, email: str | None = None) -> User:
    user = User(email=email or f"{uuid.uuid4().hex[:8]}@example.com")
    db.add(user)
    await db.flush()
    return user


async def create_workspace(db, user: User) -> Workspace:
    ws = Workspace(name="Test WS", created_by=user.id)
    db.add(ws)
    await db.flush()
    return ws


async def create_candidate(db, workspace: Workspace) -> Candidate:
    c = Candidate(
        workspace_id=workspace.id,
        full_name="Jane Doe",
        email="jane@example.com",
    )
    db.add(c)
    await db.flush()
    return c


async def create_interview(
    db, candidate: Candidate, user: User, workspace: Workspace
) -> Interview:
    interview = Interview(
        workspace_id=workspace.id,
        candidate_id=candidate.id,
        interviewer_id=user.id,
        status="in_progress",
        ai_tone="friendly",
    )
    db.add(interview)
    await db.flush()
    return interview


async def create_summary(db, interview: Interview) -> InterviewSummary:
    s = InterviewSummary(
        interview_id=interview.id,
        job_description="Software Engineer role",
        scoring_rubric="Python, FastAPI, PostgreSQL",
        status="pending",
    )
    db.add(s)
    await db.flush()
    return s


# ── tests ─────────────────────────────────────────────────────────────


RETRIEVE_PATCH = patch(
    "app.services.ai_generation_service.InterviewContextService.retrieve_relevant_chunks",
    new=AsyncMock(
        return_value=["Mocked candidate context from resume."]
    ),
)


class TestGenerateNextQuestion:
    async def test_returns_generated_question(self, db_session):
        user = await create_user(db_session)
        ws = await create_workspace(db_session, user)
        candidate = await create_candidate(db_session, ws)
        interview = await create_interview(db_session, candidate, user, ws)
        await create_summary(db_session, interview)

        with RETRIEVE_PATCH, patch(
            "app.services.ai_generation_service.generate_text",
            new=AsyncMock(return_value="What is your experience with Python?"),
        ):
            question = await AIGenerationService.generate_next_question(
                interview_id=interview.id,
                db=db_session,
                user=user,
            )

        assert question == "What is your experience with Python?"

    async def test_creates_transcript_and_turn(self, db_session):
        user = await create_user(db_session)
        ws = await create_workspace(db_session, user)
        candidate = await create_candidate(db_session, ws)
        interview = await create_interview(db_session, candidate, user, ws)
        await create_summary(db_session, interview)

        with RETRIEVE_PATCH, patch(
            "app.services.ai_generation_service.generate_text",
            new=AsyncMock(return_value="Tell me about your background."),
        ):
            await AIGenerationService.generate_next_question(
                interview_id=interview.id,
                db=db_session,
                user=user,
            )

        transcript = (
            await db_session.execute(
                __import__("sqlalchemy").select(InterviewTranscript).where(
                    InterviewTranscript.interview_id == interview.id
                )
            )
        ).scalar_one_or_none()
        assert transcript is not None

        turn = (
            await db_session.execute(
                __import__("sqlalchemy").select(InterviewTranscriptTurn).where(
                    InterviewTranscriptTurn.transcript_id == transcript.id
                )
            )
        ).scalars().first()
        assert turn is not None
        assert turn.speaker == "ai"
        assert turn.content == "Tell me about your background."
        assert turn.is_ai_question is True

    async def test_raises_404_if_interview_not_found(self, db_session):
        user = await create_user(db_session)
        fake_id = uuid.uuid4()

        with pytest.raises(APIError) as exc:
            await AIGenerationService.generate_next_question(
                interview_id=fake_id,
                db=db_session,
                user=user,
            )
        assert exc.value.status_code == 404

    async def test_raises_404_if_not_owned_by_user(self, db_session):
        user1 = await create_user(db_session, "alice@example.com")
        user2 = await create_user(db_session, "bob@example.com")
        ws = await create_workspace(db_session, user1)
        candidate = await create_candidate(db_session, ws)
        interview = await create_interview(db_session, candidate, user1, ws)
        await create_summary(db_session, interview)

        with pytest.raises(APIError) as exc:
            await AIGenerationService.generate_next_question(
                interview_id=interview.id,
                db=db_session,
                user=user2,
            )
        assert exc.value.status_code == 404

    async def test_raises_400_if_context_incomplete(self, db_session):
        user = await create_user(db_session)
        ws = await create_workspace(db_session, user)
        candidate = await create_candidate(db_session, ws)
        interview = await create_interview(db_session, candidate, user, ws)
        # No summary — incomplete context

        with pytest.raises(APIError) as exc:
            await AIGenerationService.generate_next_question(
                interview_id=interview.id,
                db=db_session,
                user=user,
            )
        assert exc.value.status_code == 400

    async def test_raises_400_if_job_description_missing(self, db_session):
        user = await create_user(db_session)
        ws = await create_workspace(db_session, user)
        candidate = await create_candidate(db_session, ws)
        interview = await create_interview(db_session, candidate, user, ws)
        summary = await create_summary(db_session, interview)
        summary.job_description = None
        await db_session.flush()

        with pytest.raises(APIError) as exc:
            await AIGenerationService.generate_next_question(
                interview_id=interview.id,
                db=db_session,
                user=user,
            )
        assert exc.value.status_code == 400


class TestGenerateAssessment:
    async def test_persists_assessment(self, db_session):
        user = await create_user(db_session)
        ws = await create_workspace(db_session, user)
        candidate = await create_candidate(db_session, ws)
        interview = await create_interview(db_session, candidate, user, ws)
        summary = await create_summary(db_session, interview)

        with RETRIEVE_PATCH, patch(
            "app.services.ai_generation_service.generate_text",
            new=AsyncMock(return_value="Strong Python skills, good communicator."),
        ):
            await AIGenerationService.generate_assessment(
                interview_id=interview.id,
                db=db_session,
            )

        await db_session.refresh(summary)
        assert summary.ai_assessment == "Strong Python skills, good communicator."
        assert summary.status == "completed"
        assert summary.generated_at is not None

    async def test_marks_failed_if_no_job_description(self, db_session):
        user = await create_user(db_session)
        ws = await create_workspace(db_session, user)
        candidate = await create_candidate(db_session, ws)
        interview = await create_interview(db_session, candidate, user, ws)
        summary = await create_summary(db_session, interview)
        summary.job_description = None
        await db_session.flush()

        await AIGenerationService.generate_assessment(
            interview_id=interview.id,
            db=db_session,
        )

        await db_session.refresh(summary)
        assert summary.status == "failed"
        assert summary.ai_assessment is None

    async def test_marks_failed_on_api_error(self, db_session):
        user = await create_user(db_session)
        ws = await create_workspace(db_session, user)
        candidate = await create_candidate(db_session, ws)
        interview = await create_interview(db_session, candidate, user, ws)
        summary = await create_summary(db_session, interview)

        with RETRIEVE_PATCH, patch(
            "app.services.ai_generation_service.generate_text",
            new=AsyncMock(side_effect=RuntimeError("API down")),
        ):
            await AIGenerationService.generate_assessment(
                interview_id=interview.id,
                db=db_session,
            )

        await db_session.refresh(summary)
        assert summary.status == "failed"

    async def test_generates_from_transcript_turns(self, db_session):
        user = await create_user(db_session)
        ws = await create_workspace(db_session, user)
        candidate = await create_candidate(db_session, ws)
        interview = await create_interview(db_session, candidate, user, ws)
        summary = await create_summary(db_session, interview)

        transcript = InterviewTranscript(
            interview_id=interview.id, status="completed"
        )
        db_session.add(transcript)
        await db_session.flush()

        turn1 = InterviewTranscriptTurn(
            transcript_id=transcript.id,
            speaker="ai",
            content="What is your experience?",
            sequence_no=1,
            is_ai_question=True,
        )
        turn2 = InterviewTranscriptTurn(
            transcript_id=transcript.id,
            speaker="candidate",
            content="I have 5 years of Python experience.",
            sequence_no=2,
            is_ai_question=False,
        )
        db_session.add_all([turn1, turn2])
        await db_session.flush()

        with RETRIEVE_PATCH, patch(
            "app.services.ai_generation_service.generate_text",
            new=AsyncMock(return_value="Good experience."),
        ):
            await AIGenerationService.generate_assessment(
                interview_id=interview.id,
                db=db_session,
            )

        await db_session.refresh(summary)
        assert summary.status == "completed"
        assert summary.ai_assessment == "Good experience."


class TestAnswerQuery:
    async def test_returns_answer(self, db_session):
        user = await create_user(db_session)
        ws = await create_workspace(db_session, user)
        candidate = await create_candidate(db_session, ws)
        interview = await create_interview(db_session, candidate, user, ws)
        await create_summary(db_session, interview)

        with patch(
            "app.services.ai_generation_service.generate_text",
            new=AsyncMock(return_value="The candidate answered well."),
        ):
            answer = await AIGenerationService.answer_query(
                interview_id=interview.id,
                query="How did the candidate do?",
                user=user,
                db=db_session,
            )
        assert answer == "The candidate answered well."

    async def test_raises_404_if_not_found(self, db_session):
        user = await create_user(db_session)

        with pytest.raises(APIError) as exc:
            await AIGenerationService.answer_query(
                interview_id=uuid.uuid4(),
                query="How did they do?",
                user=user,
                db=db_session,
            )
        assert exc.value.status_code == 404

    async def test_raises_404_if_not_owned(self, db_session):
        user1 = await create_user(db_session, "alice@example.com")
        user2 = await create_user(db_session, "bob@example.com")
        ws = await create_workspace(db_session, user1)
        candidate = await create_candidate(db_session, ws)
        interview = await create_interview(db_session, candidate, user1, ws)
        await create_summary(db_session, interview)

        with pytest.raises(APIError) as exc:
            await AIGenerationService.answer_query(
                interview_id=interview.id,
                query="How did they do?",
                user=user2,
                db=db_session,
            )
        assert exc.value.status_code == 404

    async def test_handles_empty_transcript(self, db_session):
        user = await create_user(db_session)
        ws = await create_workspace(db_session, user)
        candidate = await create_candidate(db_session, ws)
        interview = await create_interview(db_session, candidate, user, ws)
        await create_summary(db_session, interview)
        # No transcript at all

        with patch(
            "app.services.ai_generation_service.generate_text",
            new=AsyncMock(return_value="No data available."),
        ):
            answer = await AIGenerationService.answer_query(
                interview_id=interview.id,
                query="What was discussed?",
                user=user,
                db=db_session,
            )
        assert answer == "No data available."
