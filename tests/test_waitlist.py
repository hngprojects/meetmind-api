import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.integration import WaitlistSignup


@pytest.mark.anyio
class TestWaitlistAPI:
    """
    Tests for the public waitlist endpoint.

    We test three main things:
    1. Successful signup (201)
    2. Duplicate prevention (400)
    3. Invalid email format (422)
    """

    async def test_waitlist_signup_success(self, client: AsyncClient, db_session):
        email = "new_user@example.com"
        payload = {"email": email}

        response = await client.post("/api/v1/waitlist", json=payload)

        assert response.status_code == 201
        body = response.json()
        assert body["success"] is True
        assert body["data"]["email"] == email
        assert "on the list" in body["data"]["message"]

        result = await db_session.execute(
            select(WaitlistSignup).where(WaitlistSignup.email == email)
        )
        assert result.scalar_one_or_none() is not None

    async def test_waitlist_duplicate_signup_returns_400(
        self, client: AsyncClient, db_session
    ):
        email = "duplicate@example.com"
        db_session.add(WaitlistSignup(email=email, provider="email"))
        await db_session.commit()

        payload = {"email": email}
        response = await client.post("/api/v1/waitlist", json=payload)

        # Assertions
        assert response.status_code == 400
        body = response.json()
        assert body["success"] is False
        assert body["error"]["code"] == "email_already_registered"

    async def test_waitlist_invalid_email_returns_422(self, client: AsyncClient):
        payload = {"email": "not-a-valid-email"}
        response = await client.post("/api/v1/waitlist", json=payload)

        assert response.status_code == 422
        body = response.json()
        assert body["success"] is False
        assert body["error"]["code"] == "validation_error"

    async def test_waitlist_endpoint_is_public(self, client: AsyncClient):
        """
        Verify that no Authorization header is required.
        """
        payload = {"email": "public_test@example.com"}
        response = await client.post("/api/v1/waitlist", json=payload)

        assert response.status_code == 201
