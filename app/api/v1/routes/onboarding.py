from fastapi import APIRouter, BackgroundTasks

from app.api.deps import CurrentUser, DBSession
from app.core.responses import success
from app.schemas.onboarding import (
    OnboardingInviteRequest,
    OnboardingLanguageRequest,
    OnboardingPreferencesRequest,
    OnboardingRoleRequest,
    TrialActivationRequest,
)
from app.services.onboarding import OnboardingService

router = APIRouter()


@router.post("/role")
async def set_role(payload: OnboardingRoleRequest, db: DBSession, user: CurrentUser):
    await OnboardingService.set_role(payload, user, db)
    return success({"updated": True})


@router.post("/preferences")
async def set_preferences(
    payload: OnboardingPreferencesRequest, db: DBSession, user: CurrentUser
):
    await OnboardingService.set_meeting_preferences(payload, user, db)
    return success({"updated": True})


@router.post("/language")
async def set_language(
    payload: OnboardingLanguageRequest, db: DBSession, user: CurrentUser
):
    await OnboardingService.set_language(payload, user, db)
    return success({"updated": True})


@router.post("/invite")
async def invite_coworkers(
    payload: OnboardingInviteRequest,
    db: DBSession,
    user: CurrentUser,
    background_tasks: BackgroundTasks,
):
    count = await OnboardingService.invite_coworkers(
        payload, user, db, background_tasks=background_tasks
    )
    return success({"invites_sent": count})


@router.post("/trial")
async def set_trial(payload: TrialActivationRequest, db: DBSession, user: CurrentUser):
    trial = await OnboardingService.set_trial(payload, user, db)
    return success(
        {
            "is_active": trial.is_active,
            "ends_at": trial.ends_at.isoformat() if trial.ends_at else None,
        }
    )
