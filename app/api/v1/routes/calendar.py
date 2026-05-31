import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import VerifiedUser
from app.core.responses import APIResponse, success
from app.core.utils import safe_notify
from app.db.session import get_session
from app.schemas.calendar import (
    AppointmentResponse,
    AvailabilitySlot,
    CalendarUserItem,
    RescheduleRequest,
)
from app.services.calendar import CalendarService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/appointments",
    response_model=APIResponse[list[AppointmentResponse]],
    status_code=status.HTTP_200_OK,
)
async def list_appointments(
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
    filter: str = Query("all_upcoming"),
    date_filter: Optional[date] = Query(None, alias="date"),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
):
    appointments = await CalendarService.list_appointments(
        db, user, filter, date_filter, start_date, end_date
    )

    message = None
    if not appointments:
        if date_filter or filter == "today":
            message = "You don't have any interviews scheduled for this day."
        else:
            message = "You don't have any upcoming interviews."

    return success({"filter": filter, "appointments": appointments, "message": message})


@router.get(
    "/users",
    response_model=APIResponse[list[CalendarUserItem]],
    status_code=status.HTTP_200_OK,
)
async def list_users(
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
    role: Optional[str] = None,
    search: Optional[str] = None,
):
    return success(await CalendarService.list_users(db, user, role, search))


@router.get(
    "/availability",
    response_model=APIResponse[list[AvailabilitySlot]],
    status_code=status.HTTP_200_OK,
)
async def get_availability(
    user: VerifiedUser,
    target_date: date = Query(..., alias="date"),
    interviewer_id: Optional[str] = None,
    db: AsyncSession = Depends(get_session),
):
    return success(
        await CalendarService.get_availability(db, user, target_date, interviewer_id)
    )


@router.patch(
    "/appointments/{interview_id}/reschedule",
    response_model=APIResponse[AppointmentResponse],
    status_code=status.HTTP_200_OK,
)
async def reschedule_appointment(
    interview_id: str,
    payload: RescheduleRequest,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    apt = await CalendarService.reschedule_appointment(
        db, user, interview_id, payload.scheduled_start, payload.scheduled_end
    )

    await safe_notify(
        db,
        user_id=user.id,
        type="meeting",
        title="Interview Rescheduled",
        description=f" \
        {apt.get('candidate_name', '')} - {apt.get('role_title', '')}".strip(" -"),
        action_url=f"/interviews/{apt.get('id', interview_id)}",
        label="reschedule notification",
    )

    return success(apt, message="Appointment rescheduled successfully")


@router.delete(
    "/appointments/{interview_id}",
    response_model=APIResponse[AppointmentResponse],
    status_code=status.HTTP_200_OK,
)
async def cancel_appointment(
    interview_id: str, user: VerifiedUser, db: AsyncSession = Depends(get_session)
):
    apt = await CalendarService.cancel_appointment(db, user, interview_id)

    await safe_notify(
        db,
        user_id=user.id,
        type="meeting",
        title="Interview Cancelled",
        description=f" \
        {apt.get('candidate_name', '')} - {apt.get('role_title', '')}".strip(" -"),
        action_url=f"/interviews/{apt.get('id', interview_id)}",
        label="cancellation notification",
    )

    return success(apt, message="Appointment cancelled successfully")
