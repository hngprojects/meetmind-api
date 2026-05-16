from __future__ import annotations

from pydantic import BaseModel, Field


class CreateSDKSessionRequest(BaseModel):
    platform: str = Field(default="zoom")
    meeting_id: str | None = None
    meeting_url: str | None = None
    agent_name: str = Field(default="MeetMind")
    context: str | None = None
    wake_words: list[str] | None = None


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1)


class OAuthCallbackResponse(BaseModel):
    received: bool
    code_present: bool
    state: str | None = None
