import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sdk.config import get_sdk_settings
from sdk.db import SDKBase
from sdk.providers.zoom_rtms import control
from sdk.providers.zoom_rtms.control import ZoomRTMSControlClient, ZoomRTMSControlError
from sdk.providers.zoom_rtms.oauth import ZoomOAuthClient, ZoomOAuthError
from sdk.repositories import SDKRepository


@pytest.fixture
def db_session(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "SDK_TOKEN_ENCRYPTION_KEY",
        "wMs6yq2HIka7H6j9NHPmKo2Zc5e-YnJggbg0R2TiSrs=",
    )
    get_sdk_settings.cache_clear()
    engine = create_engine(f"sqlite:///{(tmp_path / 'sdk.sqlite').as_posix()}")
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    SDKBase.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        get_sdk_settings.cache_clear()


def test_zoom_oauth_client_uses_stored_access_token(db_session):
    repo = SDKRepository(db_session)
    repo.save_zoom_oauth_token(
        access_token="stored-access-token",
        refresh_token="stored-refresh-token",
        token_type="bearer",
        scope="meeting:update:participant_rtms_app_status",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )

    assert ZoomOAuthClient(db_session).get_access_token() == "stored-access-token"
    token = repo.get_latest_zoom_oauth_token()
    assert token is not None
    assert token.access_token == "stored-access-token"
    assert token.access_token_encrypted != "stored-access-token"
    assert token.access_token_encrypted.startswith("fernet:")
    assert token.refresh_token == "stored-refresh-token"
    assert token.refresh_token_encrypted != "stored-refresh-token"


def test_zoom_oauth_token_allows_null_refresh_token(db_session):
    repo = SDKRepository(db_session)
    repo.save_zoom_oauth_token(
        access_token="stored-access-token",
        refresh_token=None,
        token_type="bearer",
        scope="meeting:update:participant_rtms_app_status",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )

    token = repo.get_latest_zoom_oauth_token()
    assert token is not None
    assert token.access_token == "stored-access-token"
    assert token.refresh_token is None
    assert token.refresh_token_encrypted is None


def test_zoom_rtms_start_patches_expected_payload(monkeypatch, db_session):
    monkeypatch.setenv("ZOOM_CLIENT_ID", "test-client-id")
    get_sdk_settings.cache_clear()
    repo = SDKRepository(db_session)
    repo.save_zoom_oauth_token(
        access_token="stored-access-token",
        refresh_token="stored-refresh-token",
        token_type="bearer",
        scope="meeting:update:participant_rtms_app_status",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(202, json={"status": "requested"})

    def fake_patch(*args, **kwargs):
        transport = httpx.MockTransport(handler)
        with httpx.Client(transport=transport) as client:
            return client.patch(*args, **kwargs)

    monkeypatch.setattr(control.httpx, "patch", fake_patch)

    result = ZoomRTMSControlClient(db_session).start(meeting_id="86429575325")

    assert result["action"] == "start"
    assert result["zoom_status_code"] == 202
    assert str(requests[0].url).endswith("/live_meetings/86429575325/rtms_app/status")
    assert requests[0].headers["authorization"] == "Bearer stored-access-token"
    body = json.loads(requests[0].read().decode())
    assert body["action"] == "start"
    assert body["settings"]["client_id"] == "test-client-id"


def test_zoom_rtms_start_maps_transport_errors(monkeypatch, db_session):
    repo = SDKRepository(db_session)
    repo.save_zoom_oauth_token(
        access_token="stored-access-token",
        refresh_token="stored-refresh-token",
        token_type="bearer",
        scope="meeting:update:participant_rtms_app_status",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )

    def fake_patch(*args, **kwargs):
        raise httpx.ConnectError("connection failed")

    monkeypatch.setattr(control.httpx, "patch", fake_patch)

    with pytest.raises(ZoomRTMSControlError, match="Zoom RTMS request failed") as exc:
        ZoomRTMSControlClient(db_session).start(meeting_id="86429575325")
    assert exc.value.details["method"] == "PATCH"
    assert exc.value.details["meeting_id"] == "86429575325"
    assert exc.value.details["has_access_token"] is True


def test_zoom_rtms_start_exposes_zoom_error_details(monkeypatch, db_session):
    repo = SDKRepository(db_session)
    repo.save_zoom_oauth_token(
        access_token="stored-access-token",
        refresh_token="stored-refresh-token",
        token_type="bearer",
        scope="meeting:update:participant_rtms_app_status",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"code": 2310, "message": "Failed to perform RTMS app operation."},
        )

    def fake_patch(*args, **kwargs):
        transport = httpx.MockTransport(handler)
        with httpx.Client(transport=transport) as client:
            return client.patch(*args, **kwargs)

    monkeypatch.setattr(control.httpx, "patch", fake_patch)

    with pytest.raises(
        ZoomRTMSControlError,
        match="Failed to perform RTMS app operation.",
    ) as exc:
        ZoomRTMSControlClient(db_session).start(
            meeting_id="86429575325",
            participant_user_id="host-user-id",
        )

    assert exc.value.details["zoom_status_code"] == 400
    assert exc.value.details["zoom_response"]["code"] == 2310
    assert exc.value.details["participant_user_id"] == "host-user-id"


def test_zoom_oauth_exchange_maps_transport_errors(monkeypatch, db_session):
    from sdk.providers.zoom_rtms import oauth

    def fake_post(*args, **kwargs):
        raise httpx.ConnectError("connection failed")

    monkeypatch.setattr(oauth.httpx, "post", fake_post)

    with pytest.raises(ZoomOAuthError, match="Zoom OAuth request failed"):
        ZoomOAuthClient(db_session).exchange_code("code")
