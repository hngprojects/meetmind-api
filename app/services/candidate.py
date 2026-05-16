# app/services/candidate.py

import csv
import io
from collections.abc import AsyncGenerator
from uuid import UUID

from fastapi import status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import APIError
from app.models.interview import Candidate


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
