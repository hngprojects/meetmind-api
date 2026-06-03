from datetime import datetime

from pydantic import BaseModel


class GeneratedQuestionResponse(BaseModel):
    question: str


class RecordedResponseData(BaseModel):
    response: str


class CompleteInterviewData(BaseModel):
    status: str


class ChatAnswerData(BaseModel):
    role: str
    content: str
    sent_at: datetime
    sequence_no: int


class SummaryRetryData(BaseModel):
    interview_id: str
    status: str


class SummaryGeneratingData(BaseModel):
    status: str
