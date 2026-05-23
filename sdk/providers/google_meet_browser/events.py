from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class BotStatus(str, Enum):
    LAUNCHING = "launching"
    JOINING = "joining"
    IN_MEETING = "in_meeting"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class TranscriptEvent:
    session_id: str
    speaker: str
    text: str
    source: str
    role: str
    timestamp: datetime


@dataclass 
class StatusEvent:
    session_id: str
    status: BotStatus
    detail: str = ""


@dataclass
class ErrorEvent:
    session_id: str
    error: str
    traceback: str = ""