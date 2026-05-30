"""Schemas for onboarding step endpoints."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictBool

AllowedRole = Literal["Recruiter", "Hiring Manager", "Founder", "Other"]


class OnboardingRoleRequest(BaseModel):
    companyName: str
    role: AllowedRole
    hires: str


class PreferencesPayload(BaseModel):
    dynamic: StrictBool
    autoRecord: StrictBool
    announce: StrictBool


class OnboardingPreferencesRequest(BaseModel):
    tone: str
    preferences: PreferencesPayload


class OnboardingIntegrationsRequest(BaseModel):
    integrations: Literal["google", "zoom", "livekit"] | None


class OnboardingSubmissionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    success: bool
    onboardingCompleted: bool
