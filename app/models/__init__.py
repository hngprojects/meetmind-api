from app.models.ask_mind import AskMindMessage, AskMindSession, AskMindSuggestedPrompt
from app.models.base import Base, TimestampMixin, UUIDPrimaryKey
from app.models.document import CandidateDocument, DocumentChunk
from app.models.email_verification import EmailVerificationToken
from app.models.integration import (
    Integration,
    IntegrationChannel,
    IntegrationSettings,
    UserPlatformIntegration,
    WaitlistSignup,
)
from app.models.interview import (
    Candidate,
    Interview,
    InterviewHighlight,
    InterviewRedFlag,
    InterviewSession,
    InterviewSkillToAssess,
    InterviewSummary,
    InterviewTranscript,
    InterviewTranscriptTurn,
)
from app.models.meeting import Meeting, MeetingComment, MeetingParticipant
from app.models.notification import Notification
from app.models.scorecard import (
    InterviewScorecard,
    ScorecardCategory,
    ScorecardEvidence,
    ScorecardQuestion,
    ScorecardScore,
    ScorecardSignal,
    ScorecardSubRubric,
)
from app.models.subscription import EmailSubscription
from app.models.support import SupportTicket
from app.models.transcript import (
    ActionItem,
    MeetingSummary,
    SummaryDecision,
    SummaryKeypoint,
    Transcript,
    TranscriptSegment,
)
from app.models.user import (
    ActiveSession,
    PasswordResetToken,
    RefreshToken,
    SSOProvider,
    User,
    UserInterviewPreferences,
    UserMeetingPreferences,
    UserNotificationPreferences,
    UserPrivacySettings,
    UserSecuritySettings,
    UserTrial,
)
from app.models.workspace import Workspace, WorkspaceInvite, WorkspaceMember

__all__ = [
    "Base",
    "TimestampMixin",
    "UUIDPrimaryKey",
    # Users & Auth
    "User",
    "RefreshToken",
    "EmailVerificationToken",
    "SSOProvider",
    "PasswordResetToken",
    "ActiveSession",
    "UserMeetingPreferences",
    "UserInterviewPreferences",
    "UserNotificationPreferences",
    "UserPrivacySettings",
    "UserSecuritySettings",
    "UserTrial",
    # Subscriptions & Support
    "EmailSubscription",
    "SupportTicket",
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
    "InterviewSession",
    # Scorecards
    "ScorecardCategory",
    "InterviewScorecard",
    "ScorecardScore",
    "ScorecardQuestion",
    "ScorecardSignal",
    # Documents
    "DocumentChunk",
    "CandidateDocument",
    # Notifications
    "Notification",
]
