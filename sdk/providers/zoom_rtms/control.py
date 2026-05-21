from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy.orm import Session

from sdk.config import get_sdk_settings
from sdk.providers.zoom_rtms.oauth import ZoomOAuthClient


@dataclass
class ZoomRTMSControlError(RuntimeError):
    message: str
    details: dict[str, Any] | None = None

    def __str__(self) -> str:
        return self.message


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

        url = (
            f"{self.settings.zoom_api_base_url}/live_meetings/"
            f"{meeting_id}/rtms_app/status"
        )
        request_details = {
            "method": "PATCH",
            "url": sanitize_zoom_url(url),
            "meeting_id": meeting_id,
            "action": action,
            "participant_user_id": participant_user_id,
            "has_access_token": bool(access_token),
            "client_id_present": bool(self.settings.zoom_client_id),
        }

        try:
            response = httpx.patch(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                json=body,
                timeout=20,
            )
        except httpx.RequestError as exc:
            raise ZoomRTMSControlError(
                "Zoom RTMS request failed.",
                details={**request_details, "error": str(exc)},
            ) from exc
        response_payload = parse_zoom_response(response)
        if response.status_code >= 400:
            raise ZoomRTMSControlError(
                extract_zoom_error_message(response_payload, response.text),
                details={
                    **request_details,
                    "zoom_status_code": response.status_code,
                    "zoom_response": response_payload,
                },
            )

        return {
            "action": action,
            "meeting_id": meeting_id,
            "participant_user_id": participant_user_id,
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


def extract_zoom_error_message(response_payload: dict | None, fallback: str) -> str:
    if response_payload and response_payload.get("message"):
        return str(response_payload["message"])
    return fallback or "Zoom RTMS operation failed."


def sanitize_zoom_url(url: str) -> str:
    return url.split("?")[0]
