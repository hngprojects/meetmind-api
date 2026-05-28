from datetime import date, datetime, timedelta, timezone
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.interview import Candidate, Interview
from app.models.user import User
from app.models.workspace import WorkspaceMember


def format_time_display(start: datetime, end: datetime) -> str:
    """Computes 'Today 10:00AM - 10:30AM' or 'Mon Jun 13 10:00AM...'"""
    # Ensure datetimes are timezone aware (UTC)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)

    now_utc = datetime.now(timezone.utc)
    today = now_utc.date()
    start_date = start.date()

    # Format time (e.g., 10:00AM)
    time_str = f"{start.strftime('%I:%M%p').lstrip('0')} - {end.strftime('%I:%M%p').lstrip('0')}"

    if start_date == today:
        day_str = "Today"
    elif start_date == today + timedelta(days=1):
        day_str = "Tomorrow"
    else:
        day_str = start.strftime("%a %b %d")

    return f"{day_str} {time_str}"


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
            select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user.id)
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
            appointments.append({
                "id": str(interview.id),
                "role_title": interview.role_title,
                "status": interview.status,
                "scheduled_start": interview.scheduled_start,
                "scheduled_end": interview.scheduled_end,
                "time_display": format_time_display(interview.scheduled_start, interview.scheduled_end),
                "candidate_name": candidate.full_name,
                "candidate_email": candidate.email,
                "interviewer_name": interviewer.name,
                "interviewer_email": interviewer.email,
            })

        return appointments