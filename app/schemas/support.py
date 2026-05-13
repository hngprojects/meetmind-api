from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class ContactSupportRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    email: EmailStr
    subject: str = Field(..., min_length=3, max_length=255)
    message: str = Field(..., min_length=10, max_length=5000)


class ContactSupportResponse(BaseModel):
    id: UUID
    name: str
    email: EmailStr
    subject: str
    message: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}