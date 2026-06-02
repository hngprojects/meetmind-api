import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, computed_field

from app.services.notification_service import time_display


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
        dt = self.created_at
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return time_display(dt, now=datetime.now(timezone.utc))


class NotificationListData(BaseModel):
    notifications: list[NotificationResponse]
    unread_count: int
