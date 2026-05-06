import pytest
from app.models.user import User
from app.services.verification_service import VerificationService


def extract_response(resp_json):
    return resp_json["detail"] if "detail" in resp_json else resp_json

@pytest.mark.asyncio
async def test_verify_email_endpoint(client, db_session):
    user = User(email="api_test@example.com", is_verified=False)
    db_session.add(user)
    await db_session.commit()

    service = VerificationService()
    token = await service.create_verification_token(db_session, user.id)

    response = await client.post(
        "/api/v1/auth/verify-email",
        json={"token": token},
    )

    assert response.status_code == 200
    data = response.json()

    assert data["status_code"] == 200
    assert data["message"] == "Email verified successfully"


@pytest.mark.asyncio
async def test_verify_email_invalid_token_api(client):
    response = await client.post(
        "/api/v1/auth/verify-email",
        json={"token": "invalid"},
    )

    assert response.status_code == 400

    data = extract_response(response.json())

    assert data["status_code"] == 400

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
    data = response.json()

    assert data["status_code"] == 200