from pydantic import BaseModel, EmailStr, Field


class WaitlistRequest(BaseModel):
    email: EmailStr = Field(
        ...,
        description="Email address to register on the waitlist",
        examples=["user@example.com"],
    )


class WaitlistResponse(BaseModel):
    email: str
    message: str
