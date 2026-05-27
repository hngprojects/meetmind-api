from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import UserAlreadyExistsException
from app.models.user import User
from app.schemas.auth import ForgotPasswordRequest, LoginRequest, SignupRequest
from app.schemas.verification import ResendVerificationRequest
from app.services.auth import AuthService

# ── Helpers ───────────────────────────────────────────────────────────────────


async def create_unverified_user(db, email: str | None = None) -> User:
    user = User(email=email or f"{uuid4().hex[:8]}@example.com")
    db.add(user)
    await db.flush()
    return user


async def create_verified_user(db, email: str | None = None) -> User:
    user = User(email=email or f"{uuid4().hex[:8]}@example.com", is_verified=True)
    db.add(user)
    await db.flush()
    return user


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def make_user(**kwargs) -> User:
    user = MagicMock(spec=User)
    user.id = kwargs.get("id", uuid4())
    user.email = kwargs.get("email", "john@example.com")
    user.name = kwargs.get("name", "John Doe")
    user.password_hash = kwargs.get("password_hash", "hashed")
    return user


VALID_PAYLOAD = {
    "name": "John Doe",
    "email": "john@example.com",
    "password": "SecurePass1",
}

SIGNUP_URL = "/api/v1/auth/signup"


CREATE_USER = "app.services.auth.AuthService.create_user"
CREATE_ACCESS = "app.services.auth.AuthService.create_access_token"
CREATE_REFRESH = "app.services.auth.AuthService.create_refresh_token"

FAKE_ACCESS = "fake.access.token"
FAKE_REFRESH = "fake.refresh.token"
FAKE_REFRESH_EXPIRES = datetime.now(timezone.utc) + timedelta(days=7)
FAKE_REFRESH_TUPLE = (FAKE_REFRESH, FAKE_REFRESH_EXPIRES)


# ── Success ───────────────────────────────────────────────────────────────────


class TestSignupSuccess:
    @pytest.mark.anyio
    async def test_response_body_shape(self, client):
        user = make_user()
        with (
            patch(CREATE_USER, new_callable=AsyncMock, return_value=user),
        ):
            response = await client.post(SIGNUP_URL, json=VALID_PAYLOAD)
        body = response.json()
        data = body["data"]
        assert response.status_code == 201
        assert body["success"] is True
        assert body["message"] == "Account created successfully"
        assert "data" in body
        assert data["email"] == "john@example.com"
        assert data["name"] == "John Doe"
        assert "onboarding_completed" in data
        assert "id" in data


# ── Duplicate email ────────────────────────────────────────────────────────────


class TestSignupDuplicateEmail:
    @pytest.mark.anyio
    async def test_returns_400_when_email_already_registered(self, client):
        exc = UserAlreadyExistsException(email="john@example.com")
        with patch(CREATE_USER, new_callable=AsyncMock, side_effect=exc):
            response = await client.post(SIGNUP_URL, json=VALID_PAYLOAD)
        assert response.status_code == 400


# ── Server error ──────────────────────────────────────────────────────────────


class TestSignupServerError:
    @pytest.mark.anyio
    async def test_returns_500_on_unexpected_exception(self, client):
        with patch(
            CREATE_USER, new_callable=AsyncMock, side_effect=Exception("DB went boom")
        ):
            response = await client.post(SIGNUP_URL, json=VALID_PAYLOAD)
        assert response.status_code == 500


# ── Input validation – name ────────────────────────────────────────────────────


class TestSignupNameValidation:
    @pytest.mark.anyio
    async def test_missing_name_returns_422(self, client):
        payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "name"}
        response = await client.post(SIGNUP_URL, json=payload)
        assert response.status_code == 422


# ── Input validation – email ───────────────────────────────────────────────────


class TestSignupEmailValidation:
    @pytest.mark.anyio
    async def test_missing_email_returns_422(self, client):
        payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "email"}
        response = await client.post(SIGNUP_URL, json=payload)
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_invalid_email_format_returns_422(self, client):
        response = await client.post(
            SIGNUP_URL, json={**VALID_PAYLOAD, "email": "not-an-email"}
        )
        assert response.status_code == 422


# ── Input validation – password ────────────────────────────────────────────────


class TestSignupPasswordValidation:
    @pytest.mark.anyio
    async def test_missing_password_returns_422(self, client):
        payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "password"}
        response = await client.post(SIGNUP_URL, json=payload)
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_password_too_short_returns_422(self, client):
        response = await client.post(
            SIGNUP_URL, json={**VALID_PAYLOAD, "password": "Ab1"}
        )
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_password_without_uppercase_returns_422(self, client):
        response = await client.post(
            SIGNUP_URL, json={**VALID_PAYLOAD, "password": "lowercase1"}
        )
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_password_without_lowercase_returns_422(self, client):
        response = await client.post(
            SIGNUP_URL, json={**VALID_PAYLOAD, "password": "UPPERCASE1"}
        )
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_password_without_digit_returns_422(self, client):
        response = await client.post(
            SIGNUP_URL, json={**VALID_PAYLOAD, "password": "NoDigitPass"}
        )
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_password_at_min_length_is_accepted(self, client):
        user = make_user()
        with (
            patch(CREATE_USER, new_callable=AsyncMock, return_value=user),
            patch(CREATE_ACCESS, new_callable=AsyncMock, return_value=FAKE_ACCESS),
            patch(
                CREATE_REFRESH, new_callable=AsyncMock, return_value=FAKE_REFRESH_TUPLE
            ),
        ):
            response = await client.post(
                SIGNUP_URL, json={**VALID_PAYLOAD, "password": "Secure1!"}
            )
        assert response.status_code == 201


class TestAuthSchemaNormalization:
    def test_signup_email_is_normalized_to_lowercase_and_trimmed(self):
        payload = SignupRequest(
            name="Jane Doe",
            email="  JANE@Example.COM  ",
            password="ValidPass1",
        )
        assert payload.email == "jane@example.com"

    def test_login_email_is_normalized_to_lowercase_and_trimmed(self):
        payload = LoginRequest(email="  USER@Example.COM  ", password="ValidPass1")
        assert payload.email == "user@example.com"

    def test_forgot_password_email_is_normalized_to_lowercase_and_trimmed(self):
        payload = ForgotPasswordRequest(email="  USER@Example.COM  ")
        assert payload.email == "user@example.com"

    def test_resend_verification_email_is_normalized_to_lowercase_and_trimmed(self):
        payload = ResendVerificationRequest(email="  USER@Example.COM  ")
        assert payload.email == "user@example.com"


class TestVerificationAccess:
    @pytest.mark.anyio
    async def test_protected_route_blocks_unverified_user_with_403(
        self, client, db_session
    ):
        user = await create_unverified_user(db_session)
        token = await AuthService.create_access_token(user)
        verified_url_response = await client.get(
            "/api/v1/users/me", headers=auth_headers(token)
        )
        assert verified_url_response.status_code == 403

    @pytest.mark.anyio
    async def test_verified_user_can_access_protected_endpoints(
        self, client, db_session
    ):
        user = await create_verified_user(db_session, "verified@test.com")
        token = await AuthService.create_access_token(user)
        verified_url_response = await client.get(
            "/api/v1/users/me", headers=auth_headers(token)
        )
        assert verified_url_response.status_code == 200

        data = verified_url_response.json()["data"]

        assert data["email"] == "verified@test.com"
