from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy.orm import Session

from sdk.config import get_sdk_settings
from sdk.repositories import SDKRepository


class ZoomOAuthError(RuntimeError):
    pass


class ZoomOAuthClient:
    def __init__(self, db: Session):
        self.db = db
        self.repository = SDKRepository(db)
        self.settings = get_sdk_settings()

    def exchange_code(self, code: str) -> dict[str, Any]:
        response = httpx.post(
            self.settings.zoom_oauth_token_url,
            params={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.settings.zoom_oauth_redirect_url,
            },
            auth=(self.settings.zoom_client_id, self.settings.zoom_client_secret),
            timeout=20,
        )
        if response.status_code >= 400:
            raise ZoomOAuthError(response.text)
        token_payload = response.json()
        self._store_token(token_payload)
        return token_payload

    def get_access_token(self) -> str:
        if self.settings.zoom_access_token:
            return self.settings.zoom_access_token

        token = self.repository.get_latest_usable_zoom_oauth_token()
        if token:
            return token.access_token

        latest = self.repository.get_latest_zoom_oauth_token()
        if latest and latest.refresh_token:
            return self.refresh_access_token(latest.refresh_token)

        raise ZoomOAuthError(
            "Zoom OAuth token is missing. Visit the Zoom app authorization URL "
            "or set ZOOM_ACCESS_TOKEN for temporary testing."
        )

    def refresh_access_token(self, refresh_token: str) -> str:
        response = httpx.post(
            self.settings.zoom_oauth_token_url,
            params={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            auth=(self.settings.zoom_client_id, self.settings.zoom_client_secret),
            timeout=20,
        )
        if response.status_code >= 400:
            raise ZoomOAuthError(response.text)
        token_payload = response.json()
        self._store_token(token_payload)
        return str(token_payload["access_token"])

    def _store_token(self, token_payload: dict[str, Any]) -> None:
        expires_in = int(token_payload.get("expires_in") or 0)
        expires_at = None
        if expires_in:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)
        self.repository.save_zoom_oauth_token(
            access_token=str(token_payload["access_token"]),
            refresh_token=token_payload.get("refresh_token"),
            token_type=str(token_payload.get("token_type") or "bearer"),
            scope=token_payload.get("scope"),
            expires_at=expires_at,
        )
