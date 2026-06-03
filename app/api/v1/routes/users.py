"""User profile, preferences, and account-settings endpoints."""

from fastapi import APIRouter

from app.api.deps import VerifiedUser
from app.core.responses import APIResponse, success
from app.schemas.user import UserProfileResponse

router = APIRouter()


@router.get("/me", response_model=APIResponse[UserProfileResponse])
async def get_me(user: VerifiedUser):
    return success(
        {
            "id": str(user.id),
            "name": user.name,
            "email": user.email,
            "is_verified": user.is_verified,
            "job_title": user.job_title,
            "company": user.company,
            "avatar_url": user.avatar_url,
            "onboarding_completed": user.onboarding_completed,
        },
        message="User profile retrieved",
    )
