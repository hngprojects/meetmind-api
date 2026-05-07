"""User profile, preferences, and account-settings endpoints."""

from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.core.responses import success

router = APIRouter()


@router.get("/me")
async def get_me(user: CurrentUser):
    """Return the authenticated user's profile.

    Args:
        user: The currently authenticated user resolved by the JWT dependency.

    Returns:
        A standardized success envelope with the user's profile fields.
    """
    return success(
        {
            "id": str(user.id),
            "name": user.name,
            "email": user.email,
            "is_verified": user.is_verified,
            "job_title": user.job_title,
            "company": user.company,
            "avatar_url": user.avatar_url,
        },
        message="User profile retrieved",
    )
