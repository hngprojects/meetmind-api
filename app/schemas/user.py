from pydantic import BaseModel


class UserProfileResponse(BaseModel):
    id: str
    name: str | None
    email: str
    is_verified: bool
    job_title: str | None
    company: str | None
    avatar_url: str | None
    onboarding_completed: bool
