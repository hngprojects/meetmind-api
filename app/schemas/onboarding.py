from enum import Enum

from pydantic import BaseModel, EmailStr, Field


class UserRole(str, Enum):
    recruiter = "Recruiter"
    hr_manager = "HR Manager"
    hiring_manager = "Hiring Manager"


class JoinCondition(str, Enum):
    all_calls = "all_calls"
    scheduled_interviews = "scheduled_interviews"


class RecapRecipient(str, Enum):
    me = "me"
    everyone = "everyone"


class TrialDecision(str, Enum):
    accept = "accept"
    decline = "decline"


class OnboardingRoleRequest(BaseModel):
    role: UserRole


class OnboardingPreferencesRequest(BaseModel):
    join_condition: JoinCondition
    send_recap_to: RecapRecipient


class OnboardingLanguageRequest(BaseModel):
    language: str = Field(default="en", pattern=r"^en$")


class OnboardingInviteRequest(BaseModel):
    emails: list[EmailStr] = Field(default_factory=list, max_length=50)


class TrialActivationRequest(BaseModel):
    decision: TrialDecision
