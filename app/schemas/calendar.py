from datetime import datetime
from pydantic import BaseModel
from typing import Optional

class AppointmentResponse(BaseModel):
    id: str
    role_title: str
    status: str
    scheduled_start: datetime
    scheduled_end: datetime
    time_display: str
    candidate_name: str
    candidate_email: str | None
    interviewer_name: str | None
    interviewer_email: str | None

class AppointmentListResponse(BaseModel):
    filter: str
    appointments: list[AppointmentResponse]
    message: Optional[str] = None