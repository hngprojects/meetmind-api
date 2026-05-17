from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy.orm import Session

from sdk.config import get_sdk_settings
from sdk.providers.zoom_rtms.oauth import ZoomOAuthClient


class ZoomRTMSControlError(RuntimeError):
    pass


class ZoomRTMSControlClient:
    def __init__(self, db: Session):
        self.db = db
        self.settings = get_sdk_settings()
        self.oauth = ZoomOAuthClient(db)

    def start(
        self,
        *,
        meeting_id: str,
        participant_user_id: str | None = None,
    ) -> dict[str, Any]:
        return self.update_status(
            meeting_id=meeting_id,
            action="start",
            participant_user_id=participant_user_id,
        )

    def stop(
        self,
        *,
        meeting_id: str,
        participant_user_id: str | None = None,
    ) -> dict[str, Any]:
        return self.update_status(
            meeting_id=meeting_id,
            action="stop",
            participant_user_id=participant_user_id,
        )

    def update_status(
        self,
        *,
        meeting_id: str,
        action: str,
        participant_user_id: str | None = None,
    ) -> dict[str, Any]:
        access_token = self.oauth.get_access_token()
        body: dict[str, Any] = {
            "action": action,
            "settings": {"client_id": self.settings.zoom_client_id},
        }
        if participant_user_id:
            body["settings"]["participant_user_id"] = participant_user_id

        try:
            response = httpx.post(
                f"{self.settings.zoom_api_base_url}/live_meetings/"
                f"{meeting_id}/rtms_app/status",
                headers={"Authorization": f"Bearer {access_token}"},
                json=body,
                timeout=20,
            )
        except httpx.RequestError as exc:
            raise ZoomRTMSControlError(f"Zoom RTMS request failed: {exc}") from exc
        response_payload = parse_zoom_response(response)
        if response.status_code >= 400:
            raise ZoomRTMSControlError(str(response_payload or response.text))

        return {
            "action": action,
            "meeting_id": meeting_id,
            "zoom_status_code": response.status_code,
            "zoom_response": response_payload,
        }


def parse_zoom_response(response: httpx.Response) -> dict | None:
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return {"raw": response.text}
