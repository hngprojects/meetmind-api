from pydantic import BaseModel, Field


class TranscriptTurnRequest(BaseModel):
    speaker: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    sequence_no: int = Field(..., ge=1)
    speaker_name: str | None = None
    timestamp_sec: int | None = None
    is_ai_question: bool = False


class LiveKitTokenResponse(BaseModel):
    serverUrl: str
    roomName: str
    participantName: str
    participantToken: str


class TranscriptTurnResponse(BaseModel):
    id: str
    transcriptId: str
    deduplicated: bool


class InterviewResultResponse(BaseModel):
    status: str
    message: str
