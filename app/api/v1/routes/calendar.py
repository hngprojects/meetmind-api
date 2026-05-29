from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import VerifiedUser
from app.core.responses import success
from app.db.session import get_session
from app.schemas.calendar import RescheduleRequest
from app.services.calendar import CalendarService

router = APIRouter()

@router.get("/appointments", status_code=status.HTTP_200_OK)
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

    return success({
        "filter": filter,
        "appointments": appointments,
        "message": message
    })

@router.get("/users", status_code=status.HTTP_200_OK)
async def list_users(
    user: VerifiedUser, db: AsyncSession = Depends(get_session),
    role: Optional[str] = None, search: Optional[str] = None
):
    return success(await CalendarService.list_users(db, user, role, search))

@router.get("/availability", status_code=status.HTTP_200_OK)
async def get_availability(
    user: VerifiedUser, target_date: date = Query(..., alias="date"),
    interviewer_id: Optional[str] = None, db: AsyncSession = Depends(get_session)
):
    return success(await CalendarService.get_availability(db, user, target_date, interviewer_id))

@router.patch("/appointments/{interview_id}/reschedule", status_code=status.HTTP_200_OK)
async def reschedule_appointment(
    interview_id: str, payload: RescheduleRequest, user: VerifiedUser, db: AsyncSession = Depends(get_session)
):
    apt = await CalendarService.reschedule_appointment(db, user, interview_id, payload.scheduled_start, payload.scheduled_end)
    return success(apt, message="Appointment rescheduled successfully")

@router.delete("/appointments/{interview_id}", status_code=status.HTTP_200_OK)
async def cancel_appointment(
    interview_id: str, user: VerifiedUser, db: AsyncSession = Depends(get_session)
):
    apt = await CalendarService.cancel_appointment(db, user, interview_id)
    return success(apt, message="Appointment cancelled successfully")