import uuid
from typing import Optional

from pydantic import BaseModel, computed_field
from app.services.notification_service import time_display
from datetime import datetime, timezone

class NotificationResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    user_id: uuid.UUID
    type: str
    title: str
    description: Optional[str] = None
    is_read: bool
    action_label: Optional[str] = None
    action_url: Optional[str] = None
    created_at: datetime

    @computed_field
    @property
    def time_display(self) -> str:
        dt = self.created_at.replace(tzinfo=timezone.utc) if self.created_at.tzinfo is None else self.created_at
        return time_display(dt, now=datetime.now(timezone.utc))

