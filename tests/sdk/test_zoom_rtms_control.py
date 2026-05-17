from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sdk.db import SDKBase
from sdk.providers.zoom_rtms import control
from sdk.providers.zoom_rtms.control import ZoomRTMSControlClient
from sdk.providers.zoom_rtms.oauth import ZoomOAuthClient
from sdk.repositories import SDKRepository


@pytest.fixture
def db_session(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'sdk.sqlite').as_posix()}")
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    SDKBase.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


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


def test_zoom_rtms_start_posts_expected_payload(monkeypatch, db_session):
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

    def fake_post(*args, **kwargs):
        transport = httpx.MockTransport(handler)
        with httpx.Client(transport=transport) as client:
            return client.post(*args, **kwargs)

    monkeypatch.setattr(control.httpx, "post", fake_post)

    result = ZoomRTMSControlClient(db_session).start(meeting_id="86429575325")

    assert result["action"] == "start"
    assert result["zoom_status_code"] == 202
    assert str(requests[0].url).endswith("/live_meetings/86429575325/rtms_app/status")
    assert requests[0].headers["authorization"] == "Bearer stored-access-token"
    assert requests[0].read() == (
        b'{"action":"start","settings":{"client_id":"3iMvy78ESDa9JkWUgH3oXg"}}'
    )
