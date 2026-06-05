"""Interview report export service.

Produces Markdown strings and PDF bytes from a completed interview's DB data.
No files are written to disk — generation is fully on-demand and stateless.
"""

from __future__ import annotations

import io
import json
import logging
from datetime import datetime, timezone
from uuid import UUID

import weasyprint
from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import APIError
from app.models.interview import Candidate, Interview, InterviewSummary
from app.models.scorecard import (
    InterviewScorecard,
    ScorecardCategory,
    ScorecardQuestion,
    ScorecardScore,
    ScorecardSignal,
)
from app.models.user import User
from app.services.email_renderer import render_template
from app.services.interview import InterviewService

logger = logging.getLogger(__name__)

MAX_EXPORT_BYTES = 5 * 1024 * 1024  # 5 MB


class _ScorecardSection:
    """Lightweight container for a single scorecard section."""

    def __init__(
        self,
        title: str,
        score: int,
        questions_asked: list[str],
        signals_detected: list[str],
    ) -> None:
        self.title = title
        self.score = score
        self.questions_asked = questions_asked
        self.signals_detected = signals_detected


class _ReportData:
    """All data needed to render either format, collected once."""

    def __init__(
        self,
        interview: Interview,
        candidate: Candidate | None,
        summary: InterviewSummary,
        scorecard_sections: list[_ScorecardSection],
    ) -> None:
        assessment = _parse_assessment(summary.ai_assessment)

        self.role_title = interview.role_title or "Interview"
        self.status = interview.status or "unknown"
        self.platform = interview.platform
        self.candidate_name = candidate.full_name if candidate else "Unknown"
        self.candidate_email = candidate.email if candidate else None
        self.candidate_phone = candidate.phone if candidate else None
        self.job_description = summary.job_description
        self.observation: str | None = assessment.get("observation")
        self.highlights: list[str] = assessment.get("highlights") or []
        self.red_flags: list[str] = assessment.get("red_flags") or []
        self.scorecard_sections = scorecard_sections
        self.generated_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.scheduled_date: str | None = (
            interview.scheduled_start.strftime("%Y-%m-%d %H:%M UTC")
            if interview.scheduled_start
            else None
        )


def _parse_assessment(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}


async def _load_scorecard_sections(
    interview: Interview,
    db: AsyncSession,
) -> list[_ScorecardSection]:
    """Query scorecard, scores, questions, and signals for one interview."""
    sc_result = await db.execute(
        select(InterviewScorecard).where(
            InterviewScorecard.interview_id == interview.id
        )
    )
    scorecard = sc_result.scalar_one_or_none()
    if not scorecard:
        return []

    scores_result = await db.execute(
        select(ScorecardScore)
        .join(ScorecardCategory, ScorecardScore.category_id == ScorecardCategory.id)
        .where(ScorecardScore.scorecard_id == scorecard.id)
        .order_by(ScorecardCategory.sort_order)
    )
    scores = scores_result.scalars().all()

    sections: list[_ScorecardSection] = []
    for score in scores:
        category = await db.get(ScorecardCategory, score.category_id)
        category_name = category.name if category else "Unknown"

        questions_result = await db.execute(
            select(ScorecardQuestion)
            .where(ScorecardQuestion.score_id == score.id)
            .order_by(ScorecardQuestion.sort_order)
        )
        questions = [q.content for q in questions_result.scalars().all()]

        signals_result = await db.execute(
            select(ScorecardSignal)
            .where(ScorecardSignal.score_id == score.id)
            .order_by(ScorecardSignal.sort_order)
        )
        signals = [s.label for s in signals_result.scalars().all()]

        sections.append(
            _ScorecardSection(
                title=category_name,
                score=score.score_pct or 0,
                questions_asked=questions,
                signals_detected=signals,
            )
        )

    return sections


async def _collect(
    interview_id: UUID,
    db: AsyncSession,
    user: User,
) -> _ReportData:
    """Fetch all report data from the DB. Raises APIError on any guard failure."""
    interview = await InterviewService.fetch_interview(interview_id, db, user)

    candidate = (
        await db.get(Candidate, interview.candidate_id)
        if interview.candidate_id
        else None
    )

    summary = await InterviewService.get_summary(interview_id, db)
    if not summary or not summary.ai_assessment:
        raise APIError(
            "No summary available for this interview. "
            "The assessment may still be generating or may have failed.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="summary_not_ready",
        )

    scorecard_sections = await _load_scorecard_sections(interview, db)

    return _ReportData(interview, candidate, summary, scorecard_sections)


class ExportService:
    @staticmethod
    async def build_markdown(
        interview_id: UUID,
        db: AsyncSession,
        user: User,
    ) -> str:
        logger.info(
            "Export requested interview_id=%s format=markdown user_id=%s",
            interview_id,
            user.id,
        )

        data = await _collect(interview_id, db, user)

        buf = io.StringIO()
        w = buf.write

        w(f"# Interview Report: {data.role_title}\n")
        w(f"Generated: {data.generated_date}\n\n")

        # 1. Overview
        w("## Interview Overview\n\n")
        w(f"- **Candidate:** {data.candidate_name}\n")
        w(f"- **Email:** {data.candidate_email or 'N/A'}\n")
        w(f"- **Phone:** {data.candidate_phone or 'N/A'}\n")
        w(f"- **Role:** {data.role_title}\n")
        w(f"- **Platform:** {data.platform or 'N/A'}\n")
        w(f"- **Scheduled:** {data.scheduled_date or 'N/A'}\n")
        w(f"- **Status:** {data.status}\n\n")

        # 2. Job Description
        w("## Job Description\n\n")
        w(f"{data.job_description or '_Not provided._'}\n\n")

        # 3. Key Insights
        w("## Key Insights\n\n")
        w(f"{data.observation or '_Assessment not yet generated._'}\n\n")

        # 4. Strengths
        w("## Strengths\n\n")
        if data.highlights:
            for h in data.highlights:
                w(f"- {h}\n")
        else:
            w("_None recorded._\n")
        w("\n")

        # 5. Areas of Concern
        w("## Areas of Concern\n\n")
        if data.red_flags:
            for r in data.red_flags:
                w(f"- {r}\n")
        else:
            w("_None recorded._\n")
        w("\n")

        # 6. Scorecard
        w("## Scorecard\n\n")
        if data.scorecard_sections:
            for section in data.scorecard_sections:
                w(f"### {section.title} — {section.score}%\n\n")
                if section.questions_asked:
                    w("**Questions Asked:**\n\n")
                    for q in section.questions_asked:
                        w(f"- {q}\n")
                    w("\n")
                if section.signals_detected:
                    w("**Signals Detected:**\n\n")
                    for s in section.signals_detected:
                        w(f"- {s}\n")
                    w("\n")
        else:
            w("_No scorecard data available._\n\n")

        w("---\n")
        w(
            f"_Confidential · Generated by MeetMind AI Interviewer · \
                {data.generated_date}_\n"
        )

        return buf.getvalue()

    @staticmethod
    async def build_pdf(
        interview_id: UUID,
        db: AsyncSession,
        user: User,
    ) -> bytes:
        logger.info(
            "Export requested interview_id=%s format=pdf user_id=%s",
            interview_id,
            user.id,
        )

        data = await _collect(interview_id, db, user)

        try:
            html = render_template(
                "reports/interview_report.html",
                role_title=data.role_title,
                generated_date=data.generated_date,
                candidate_name=data.candidate_name,
                candidate_email=data.candidate_email,
                candidate_phone=data.candidate_phone,
                platform=data.platform,
                scheduled_date=data.scheduled_date,
                status=data.status,
                job_description=data.job_description,
                observation=data.observation,
                highlights=data.highlights,
                red_flags=data.red_flags,
                scorecard_sections=data.scorecard_sections,
            )
            pdf_bytes: bytes = weasyprint.HTML(string=html).write_pdf()
        except Exception as exc:
            logger.exception("PDF generation failed for interview_id=%s", interview_id)
            raise APIError(
                "Failed to generate PDF report",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                code="export_failed",
            ) from exc

        if len(pdf_bytes) > MAX_EXPORT_BYTES:
            raise APIError(
                "Generated file exceeds the 5MB limit",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="export_too_large",
            )

        return pdf_bytes
