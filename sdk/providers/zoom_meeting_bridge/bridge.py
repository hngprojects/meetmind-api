from __future__ import annotations


class MeetingOutputBridge:
    """Interface for the v0.2 Zoom Meeting SDK speaking bridge."""

    def speak(self, *, session_id: str, text: str) -> dict:
        raise NotImplementedError(
            "Zoom speaking requires the Meeting SDK bridge implementation."
        )
