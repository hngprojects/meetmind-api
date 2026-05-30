import pytest

from app.core.config import settings
from app.models.user import User
from app.services.verification_service import VerificationService


@pytest.mark.asyncio
async def test_verify_email_endpoint(client, db_session):
    user = User(email="api_test@example.com", is_verified=False)
    db_session.add(user)
    await db_session.commit()

    service = VerificationService()
    token = await service.create_verification_token(db_session, user)

    response = await client.post(
        "/api/v1/auth/verify-email",
        json={"token": token},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["message"] == "Email verified successfully"


@pytest.mark.asyncio
async def test_verify_email_invalid_token_api(client):
    response = await client.post(
        "/api/v1/auth/verify-email",
        json={"token": "invalid"},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "invalid_verification_token"


@pytest.mark.asyncio
async def test_resend_verification_api(client, db_session):
    user = User(email="resend@example.com", is_verified=False)
    db_session.add(user)
    await db_session.commit()

    response = await client.post(
        "/api/v1/auth/resend-verification",
        json={"email": user.email},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["message"] == "Verification email resent"


@pytest.mark.asyncio
async def test_verify_email_sends_welcome_email(client, db_session):
    from unittest.mock import AsyncMock, patch

    user = User(
        email="welcome_api_test@example.com",
        name="Welcome User",
        is_verified=False,
    )
    db_session.add(user)
    await db_session.commit()

    service = VerificationService()
    token = await service.create_verification_token(db_session, user)

    with patch(
        "app.services.verification_service.send_welcome_email",
        new=AsyncMock(),
    ) as mock_send_welcome:
        response = await client.post(
            "/api/v1/auth/verify-email",
            json={"token": token},
        )

    assert response.status_code == 200
    mock_send_welcome.assert_awaited_once()
    args, kwargs = mock_send_welcome.await_args
    assert args[:3] == (
        user.email,
        user.name,
        f"{settings.FRONTEND_URL.rstrip('/')}/dashboard",
    )
    assert "background_tasks" in kwargs
