import uuid
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.avatar import get_avatar_color, get_avatar_initials
from app.core.responses import APIError
from app.core.utils import compute_available_slots, format_time_display
from app.models.interview import Candidate, Interview
from app.models.user import User
from app.models.workspace import WorkspaceMember


class CalendarService:
    @staticmethod
    async def list_appointments(
        db: AsyncSession,
        user: User,
        filter_type: str = "all_upcoming",
        target_date: date | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict]:

        # 1. Scope to workspace
        workspace_id = await db.scalar(
            select(WorkspaceMember.workspace_id).where(
                WorkspaceMember.user_id == user.id
            )
        )
        if not workspace_id:
            return []

        # 2. Base Query
        query = (
            select(Interview, Candidate, User)
            .join(Candidate, Interview.candidate_id == Candidate.id)
            .join(User, Interview.interviewer_id == User.id)
            .where(Interview.workspace_id == workspace_id)
            .where(Interview.scheduled_start.is_not(None))
            .where(Interview.scheduled_end.is_not(None))
        )

        now = datetime.now(timezone.utc)
        today = now.date()

        # 3. Apply Filters
        if target_date:
            query = query.where(func.date(Interview.scheduled_start) == target_date)
        elif start_date and end_date:
            query = query.where(func.date(Interview.scheduled_start) >= start_date)
            query = query.where(func.date(Interview.scheduled_start) <= end_date)
        elif filter_type == "today":
            query = query.where(func.date(Interview.scheduled_start) == today)
        else:
            # Default: all_upcoming
            query = query.where(Interview.scheduled_start >= now)

        query = query.order_by(Interview.scheduled_start.asc())

        result = await db.execute(query)
        rows = result.all()

        # 4. Format Output
        appointments = []
        for interview, candidate, interviewer in rows:
            appointments.append(
                {
                    "id": str(interview.id),
                    "role_title": interview.role_title,
                    "status": interview.status,
                    "scheduled_start": interview.scheduled_start,
                    "scheduled_end": interview.scheduled_end,
                    "time_display": format_time_display(
                        interview.scheduled_start, interview.scheduled_end
                    ),
                    "candidate_name": candidate.full_name,
                    "candidate_email": candidate.email,
                    "interviewer_name": interviewer.name,
                    "interviewer_email": interviewer.email,
                }
            )

        return appointments

    @staticmethod
    async def list_users(
        db: AsyncSession, user: User, role: str | None, search: str | None
    ) -> list[dict]:
        workspace_id = await db.scalar(
            select(WorkspaceMember.workspace_id).where(
                WorkspaceMember.user_id == user.id
            )
        )
        if not workspace_id:
            return []

        query = (
            select(User, WorkspaceMember.role)
            .join(WorkspaceMember)
            .where(WorkspaceMember.workspace_id == workspace_id)
        )
        if role:
            query = query.where(WorkspaceMember.role == role)
        if search:
            query = query.where(User.name.ilike(f"%{search}%"))

        rows = (await db.execute(query)).all()
        return [
            {
                "id": str(u.id),
                "name": u.name,
                "email": u.email,
                "role": m_role,
                "avatar_initials": get_avatar_initials(u.name, u.email),
                "avatar_color": get_avatar_color(u.id),
            }
            for u, m_role in rows
        ]

    @staticmethod
    async def get_availability(
        db: AsyncSession, user: User, target_date: date, interviewer_id: str | None
    ) -> list[dict]:
        i_id = uuid.UUID(interviewer_id) if interviewer_id else user.id
        query = (
            select(Interview.scheduled_start, Interview.scheduled_end)
            .where(Interview.interviewer_id == i_id)
            .where(Interview.status != "cancelled")
            .where(func.date(Interview.scheduled_start) == target_date)
        )
        booked = (await db.execute(query)).all()
        intervals = [
            (
                s.replace(tzinfo=timezone.utc) if s.tzinfo is None else s,
                e.replace(tzinfo=timezone.utc) if e.tzinfo is None else e,
            )
            for s, e in booked
        ]
        return compute_available_slots(intervals, target_date)

    @staticmethod
    async def _check_conflict(
        db: AsyncSession,
        interviewer_id: uuid.UUID,
        start: datetime,
        end: datetime,
        exclude_interview_id: uuid.UUID | None = None,
    ) -> bool:
        """Helper to detect overlapping bookings for an interviewer."""
        query = select(Interview).where(
            Interview.interviewer_id == interviewer_id,
            Interview.status != "cancelled",
            Interview.scheduled_start < end,
            Interview.scheduled_end > start,
        )
        if exclude_interview_id:
            query = query.where(Interview.id != exclude_interview_id)

        conflict = await db.scalar(query)
        return bool(conflict)

    @classmethod
    async def reschedule_appointment(
        cls,
        db: AsyncSession,
        user: User,
        interview_id: str,
        new_start: datetime,
        new_end: datetime,
    ) -> dict:
        workspace_id = await db.scalar(
            select(WorkspaceMember.workspace_id).where(
                WorkspaceMember.user_id == user.id
            )
        )

        # Ensure UTC
        if new_start.tzinfo is None:
            new_start = new_start.replace(tzinfo=timezone.utc)
        if new_end.tzinfo is None:
            new_end = new_end.replace(tzinfo=timezone.utc)

        # Fetch interview joined with candidate and interviewer for the return shape
        query = (
            select(Interview, Candidate, User)
            .join(Candidate, Interview.candidate_id == Candidate.id)
            .join(User, Interview.interviewer_id == User.id)
            .where(
                Interview.id == uuid.UUID(interview_id),
                Interview.workspace_id == workspace_id,
            )
        )
        row = (await db.execute(query)).first()

        if not row:
            raise APIError("Appointment not found", status_code=404)

        interview, candidate, interviewer = row

        if interview.status == "cancelled":
            raise APIError("Cannot reschedule a cancelled interview", status_code=409)

        if interview.status == "completed":
            raise APIError("Cannot reschedule a cancelled interview", status_code=409)

        # Conflict check (exclude self)
        conflict = await cls._check_conflict(
            db,
            interview.interviewer_id,
            new_start,
            new_end,
            exclude_interview_id=interview.id,
        )
        if conflict:
            raise APIError("Interviewer has a conflicting booking", status_code=409)

        interview.scheduled_start = new_start
        interview.scheduled_end = new_end
        interview.rescheduled_at = func.now()
        await db.commit()
        await db.refresh(interview)

        return {
            "id": str(interview.id),
            "role_title": interview.role_title,
            "status": interview.status,
            "scheduled_start": interview.scheduled_start,
            "scheduled_end": interview.scheduled_end,
            "time_display": format_time_display(
                interview.scheduled_start, interview.scheduled_end
            ),
            "candidate_name": candidate.full_name,
            "candidate_email": candidate.email,
            "interviewer_name": interviewer.name,
            "interviewer_email": interviewer.email,
        }

    @classmethod
    async def cancel_appointment(
        cls, db: AsyncSession, user: User, interview_id: str
    ) -> dict:
        workspace_id = await db.scalar(
            select(WorkspaceMember.workspace_id).where(
                WorkspaceMember.user_id == user.id
            )
        )

        query = (
            select(Interview, Candidate, User)
            .join(Candidate, Interview.candidate_id == Candidate.id)
            .join(User, Interview.interviewer_id == User.id)
            .where(
                Interview.id == uuid.UUID(interview_id),
                Interview.workspace_id == workspace_id,
            )
        )
        row = (await db.execute(query)).first()

        if not row:
            raise APIError("Appointment not found", status_code=404)

        interview, candidate, interviewer = row

        if interview.status == "cancelled":
            raise APIError("Appointment is already cancelled", status_code=409)

        if interview.status == "completed":
            raise APIError("Cannot reschedule a cancelled interview", status_code=409)

        interview.status = "cancelled"
        await db.commit()
        await db.refresh(interview)

        return {
            "id": str(interview.id),
            "role_title": interview.role_title,
            "status": interview.status,
            "scheduled_start": interview.scheduled_start,
            "scheduled_end": interview.scheduled_end,
            "time_display": format_time_display(
                interview.scheduled_start, interview.scheduled_end
            ),
            "candidate_name": candidate.full_name,
            "candidate_email": candidate.email,
            "interviewer_name": interviewer.name,
            "interviewer_email": interviewer.email,
        }
