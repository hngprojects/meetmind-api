"""Onboarding service operations."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integration import UserPlatformIntegration
from app.models.user import User, UserInterviewPreferences, UserMeetingPreferences
from app.schemas.onboarding import (
    OnboardingIntegrationsRequest,
    OnboardingPreferencesRequest,
    OnboardingRoleRequest,
)


class OnboardingService:
    @staticmethod
    async def set_role(
        db: AsyncSession, user: User, payload: OnboardingRoleRequest
    ) -> None:
        user.company = payload.companyName
        user.role = payload.role
        user.hires = payload.hires
        await db.commit()

    @staticmethod
    async def set_meeting_preferences(
        db: AsyncSession, user: User, payload: OnboardingPreferencesRequest
    ) -> None:
        result = await db.execute(
            select(UserMeetingPreferences).where(
                UserMeetingPreferences.user_id == user.id
            )
        )
        meeting_pref = result.scalar_one_or_none()
        if not meeting_pref:
            meeting_pref = UserMeetingPreferences(user_id=user.id)
            db.add(meeting_pref)

        meeting_pref.unlimited_transcripts = payload.preferences.dynamic
        meeting_pref.auto_record = payload.preferences.autoRecord
        meeting_pref.announce = payload.preferences.announce

        interview_result = await db.execute(
            select(UserInterviewPreferences).where(
                UserInterviewPreferences.user_id == user.id
            )
        )
        interview_pref = interview_result.scalar_one_or_none()
        if not interview_pref:
            interview_pref = UserInterviewPreferences(user_id=user.id)
            db.add(interview_pref)

        interview_pref.tone = payload.tone
        await db.commit()

    @staticmethod
    async def save_integrations(
        db: AsyncSession, user: User, payload: OnboardingIntegrationsRequest
    ) -> None:
        if payload.integrations is None:
            await db.commit()
            return
        result = await db.execute(
            select(UserPlatformIntegration).where(
                UserPlatformIntegration.user_id == user.id,
                UserPlatformIntegration.platform == payload.integrations,
            )
        )
        integration = result.scalar_one_or_none()
        if not integration:
            integration = UserPlatformIntegration(
                user_id=user.id, platform=payload.integrations, status="connected"
            )
            db.add(integration)
        else:
            integration.status = "connected"
        await db.commit()

    @staticmethod
    async def complete_submission(db: AsyncSession, user: User) -> None:
        user.onboarding_completed = True
        await db.commit()
