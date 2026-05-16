from datetime import UTC, datetime, timedelta

from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserMeetingPreferences, UserTrial
from app.models.workspace import Workspace, WorkspaceInvite
from app.schemas.onboarding import (
    OnboardingInviteRequest,
    OnboardingLanguageRequest,
    OnboardingPreferencesRequest,
    OnboardingRoleRequest,
    TrialActivationRequest,
)
from app.services.email_service import _send_email


class OnboardingService:
    @staticmethod
    async def set_role(
        payload: OnboardingRoleRequest, user: User, db: AsyncSession
    ) -> None:
        user.role = payload.role.value
        await db.commit()

    @staticmethod
    async def set_meeting_preferences(
        payload: OnboardingPreferencesRequest, user: User, db: AsyncSession
    ) -> None:
        result = await db.execute(
            select(UserMeetingPreferences).where(
                UserMeetingPreferences.user_id == user.id
            )
        )
        pref = result.scalar_one_or_none()
        if pref is None:
            pref = UserMeetingPreferences(user_id=user.id)
            db.add(pref)
        pref.join_condition = payload.join_condition.value
        pref.send_recap_to = payload.send_recap_to.value
        await db.commit()

    @staticmethod
    async def set_language(
        payload: OnboardingLanguageRequest, user: User, db: AsyncSession
    ) -> None:
        user.language = payload.language
        await db.commit()

    @staticmethod
    async def invite_coworkers(
        payload: OnboardingInviteRequest,
        user: User,
        db: AsyncSession,
        background_tasks: BackgroundTasks | None = None,
    ) -> int:
        result = await db.execute(
            select(Workspace).where(Workspace.created_by == user.id)
        )
        workspace = result.scalar_one_or_none()
        if workspace is None:
            workspace = Workspace(
                name=f"{user.name} o 'MeetMind' Workspace", created_by=user.id
            )
            db.add(workspace)
            await db.flush()

        created = 0
        for email in payload.emails:
            invite = WorkspaceInvite(
                workspace_id=workspace.id, invited_by=user.id, email=str(email)
            )
            db.add(invite)
            created += 1
            subject = f"{user.name or user.email} invited you to MeetMind"
            html = f"<p>You were invited to join a MeetMind workspace by \
                {user.name or user.email}.</p>"
            if background_tasks:
                background_tasks.add(_send_email, str(email), subject, html)
            else:
                await _send_email(str(email), subject, html)

        await db.commit()
        return created

    @staticmethod
    async def set_trial(
        payload: TrialActivationRequest, user: User, db: AsyncSession
    ) -> UserTrial:
        result = await db.execute(select(UserTrial).where(UserTrial.user_id == user.id))
        trial = result.scalar_one_or_none()
        if trial is None:
            trial = UserTrial(user_id=user.id)
            db.add(trial)

        if payload.decision.value == "accept":
            now = datetime.now(UTC)
            trial.started_at = now
            trial.ends_at = now + timedelta(days=7)
            trial.is_active = True
        else:
            trial.is_active = False
        user.onboarding_completed = True
        await db.commit()
        await db.refresh(trial)
        return trial
