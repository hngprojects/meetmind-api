from app.models.base import Base, TimestampMixin, UUIDPrimaryKey
from app.models.user import (
    ActiveSession,
    PasswordResetToken,
    SSOProvider,
    User,
    UserInterviewPreferences,
    UserMeetingPreferences,
    UserNotificationPreferences,
    UserPrivacySettings,
    UserSecuritySettings,
)
from app.models.workspace import Workspace, WorkspaceInvite, WorkspaceMember
from app.models.integration import (
    Integration,
    IntegrationChannel,
    IntegrationSettings,
    UserPlatformIntegration,
    WaitlistSignup,
)
from app.models.meeting import Meeting, MeetingComment, MeetingParticipant
from app.models.transcript import (
    ActionItem,
    MeetingSummary,
    SummaryDecision,
    SummaryKeypoint,
    Transcript,
    TranscriptSegment,
)
from app.models.ask_mind import AskMindMessage, AskMindSession, AskMindSuggestedPrompt
from app.models.interview import (
    Candidate,
    Interview,
    InterviewHighlight,
    InterviewRedFlag,
    InterviewSkillToAssess,
    InterviewSummary,
    InterviewTranscript,
    InterviewTranscriptTurn,
)
from app.models.scorecard import (
    InterviewScorecard,
    ScorecardCategory,
    ScorecardQuestion,
    ScorecardScore,
    ScorecardSignal,
)

__all__ = [
    "Base",
    "TimestampMixin",
    "UUIDPrimaryKey",
    # Users & Auth
    "User",
    "SSOProvider",
    "PasswordResetToken",
    "ActiveSession",
    "UserMeetingPreferences",
    "UserInterviewPreferences",
    "UserNotificationPreferences",
    "UserPrivacySettings",
    "UserSecuritySettings",
    # Workspaces
    "Workspace",
    "WorkspaceMember",
    "WorkspaceInvite",
    # Integrations
    "UserPlatformIntegration",
    "Integration",
    "IntegrationChannel",
    "IntegrationSettings",
    "WaitlistSignup",
    # Meetings
    "Meeting",
    "MeetingParticipant",
    "MeetingComment",
    # Transcripts & Summaries
    "Transcript",
    "TranscriptSegment",
    "MeetingSummary",
    "SummaryKeypoint",
    "SummaryDecision",
    "ActionItem",
    # Ask Mind
    "AskMindSession",
    "AskMindMessage",
    "AskMindSuggestedPrompt",
    # Interviews
    "Candidate",
    "Interview",
    "InterviewTranscript",
    "InterviewTranscriptTurn",
    "InterviewSummary",
    "InterviewSkillToAssess",
    "InterviewHighlight",
    "InterviewRedFlag",
    # Scorecards
    "ScorecardCategory",
    "InterviewScorecard",
    "ScorecardScore",
    "ScorecardQuestion",
    "ScorecardSignal",
]
