# app/services/candidate.py

import csv
import io
from collections.abc import AsyncGenerator

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.interview import Candidate, Interview


class CandidateService:
    @staticmethod
    async def search(
        db: AsyncSession,
        q: str,
        workspace_id,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Candidate], int]:

        pattern = f"%{q.strip()}%"

        # Base query — scoped to workspace
        base_query = select(Candidate).where(
            Candidate.workspace_id == workspace_id,
            or_(
                Candidate.full_name.ilike(pattern),
                Candidate.email.ilike(pattern),
            ),
        )

        # Count query — same filters, no pagination
        # We need the total count to calculate total_pages in the response
        count_query = select(func.count(Candidate.id)).where(
            Candidate.workspace_id == workspace_id,
            or_(
                Candidate.full_name.ilike(pattern),
                Candidate.email.ilike(pattern),
            ),
        )

        count_result = await db.execute(count_query)
        total = count_result.scalar() or 0

        # Paginated query — offset/limit for the current page
        # offset = how many rows to skip = (page - 1) * page_size
        # Example: page=2, page_size=20 → skip 20, take next 20
        offset = (page - 1) * page_size
        paginated_query = base_query.offset(offset).limit(page_size)

        result = await db.execute(paginated_query)
        candidates = result.scalars().all()

        return list(candidates), total

    @staticmethod
    async def export_csv_generator(
        db: AsyncSession,
        workspace_id,
        q: str | None = None,
    ) -> AsyncGenerator[str, None]:

        # Yield the CSV header first
        header_buffer = io.StringIO()
        writer = csv.writer(header_buffer)
        writer.writerow(
            [
                "id",
                "full_name",
                "email",
                "phone",
                "workspace_id",
                "created_at",
            ]
        )
        yield header_buffer.getvalue()

        # Build the data query — optionally filtered by search term
        query = select(Candidate).where(Candidate.workspace_id == workspace_id)

        if q:
            pattern = f"%{q.strip()}%"
            query = query.where(
                or_(
                    Candidate.full_name.ilike(pattern),
                    Candidate.email.ilike(pattern),
                )
            )

        # Use scalars() to get one ORM object at a time
        # This avoids loading all rows at once
        result = await db.execute(query)
        candidates = result.scalars().all()

        for candidate in candidates:
            row_buffer = io.StringIO()
            writer = csv.writer(row_buffer)
            writer.writerow(
                [
                    str(candidate.id),
                    candidate.full_name,
                    candidate.email or "",
                    candidate.phone or "",
                    str(candidate.workspace_id),
                    candidate.created_at.isoformat() if candidate.created_at else "",
                ]
            )
            yield row_buffer.getvalue()

    @staticmethod
    async def list_candidates(
        db: AsyncSession,
        workspace_id,
        q: str | None = None,
        status: str | None = None,
        sort_by: str | None = "date",
        sort_direction: str | None = "desc",
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict], int]:

        # Subquery to get the most recent interview per candidate
        latest_interview_subquery = (
            select(
                Interview.candidate_id,
                func.max(Interview.created_at).label("max_created_at"),
            )
            .where(Interview.workspace_id == workspace_id)
            .group_by(Interview.candidate_id)
            .subquery()
        )

        # Join candidates to their most recent interview
        latest_interview = aliased(Interview)
        base_query = (
            select(Candidate, latest_interview)
            .outerjoin(
                latest_interview_subquery,
                Candidate.id == latest_interview_subquery.c.candidate_id,
            )
            .outerjoin(
                latest_interview,
                and_(
                    latest_interview.candidate_id == Candidate.id,
                    latest_interview.created_at
                    == latest_interview_subquery.c.max_created_at,
                ),
            )
            .where(Candidate.workspace_id == workspace_id)
        )

        # Search filter
        if q:
            pattern = f"%{q.strip()}%"
            base_query = base_query.where(
                or_(
                    Candidate.full_name.ilike(pattern),
                    Candidate.email.ilike(pattern),
                    latest_interview.role_title.ilike(pattern),
                )
            )

        # Status filter — map FE status to interview status
        status_map = {
            "ongoing": "in_progress",
            "completed": "completed",
            "needs_review": "needs_attention",
        }
        if status and status in status_map:
            base_query = base_query.where(latest_interview.status == status_map[status])

        # Sorting
        sort_column_map = {
            "date": Candidate.created_at,
            "name": Candidate.full_name,
            "score": latest_interview.rating,
        }
        sort_column = sort_column_map.get(sort_by or "date", Candidate.created_at)
        if sort_direction == "asc":
            base_query = base_query.order_by(sort_column.asc().nulls_last())
        else:
            base_query = base_query.order_by(sort_column.desc().nulls_last())

        # Count query
        count_result = await db.execute(
            select(func.count()).select_from(base_query.subquery())
        )
        total = count_result.scalar() or 0

        # Paginated query
        offset = (page - 1) * page_size
        result = await db.execute(base_query.offset(offset).limit(page_size))
        rows = result.all()

        # Map to FE shape
        interview_status_map = {
            "in_progress": "ongoing",
            "completed": "completed",
            "needs_attention": "needs_review",
        }

        candidates = []
        for candidate, interview in rows:
            candidates.append(
                {
                    "id": str(candidate.id),
                    "name": candidate.full_name,
                    "email": candidate.email,
                    "role": interview.role_title if interview else None,
                    "status": interview_status_map.get(interview.status, "ongoing")
                    if interview
                    else "ongoing",
                    "score": interview.rating if interview else None,
                    "action": "none",
                    "created_at": candidate.created_at.isoformat()
                    if candidate.created_at
                    else None,
                    "avatar_url": candidate.avatar_initials,
                    "notes": None,
                }
            )

        return candidates, total
