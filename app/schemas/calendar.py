from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator


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


class RescheduleRequest(BaseModel):
    scheduled_start: datetime
    scheduled_end: datetime

    @field_validator("scheduled_end")
    @classmethod
    def end_must_be_after_start(cls, v, info):
        if "scheduled_start" in info.data and v <= info.data["scheduled_start"]:
            raise ValueError("scheduled_end must be after scheduled_start")
        return v
