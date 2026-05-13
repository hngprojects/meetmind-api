from pydantic import BaseModel, EmailStr


class SubscriptionRequest(BaseModel):
    email: EmailStr
