"""Extract and persist the interview transcript.

Transcript is taken from the AgentSession chat history: role "user" = candidate,
role "assistant" = interviewer.
"""

import json
import time
from pathlib import Path

TRANSCRIPTS_DIR = Path(__file__).parent / "transcripts"


def extract_turns(history) -> list[dict]:
    """Decode an AgentSession chat history into [{speaker, text}, ...]."""
    turns: list[dict] = []
    for item in getattr(history, "items", []):
        role = getattr(item, "role", None)
        if role not in ("user", "assistant"):
            continue
        text = _item_text(item).strip()
        if not text:
            continue
        turns.append(
            {
                "speaker": "candidate" if role == "user" else "interviewer",
                "text": text,
            }
        )
    return turns


def save_transcript(session_id: str, turns: list[dict]) -> Path:
    """Write a local JSON backup of the transcript."""
    TRANSCRIPTS_DIR.mkdir(exist_ok=True)
    path = TRANSCRIPTS_DIR / f"{session_id}-{int(time.time())}.json"
    path.write_text(
        json.dumps(
            {
                "session_id": session_id,
                "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "turns": turns,
            },
            indent=2,
        )
    )
    return path


def _item_text(item) -> str:
    content = getattr(item, "content", item)
    if isinstance(content, (list, tuple)):
        return " ".join(str(c) for c in content)
    return str(content)
