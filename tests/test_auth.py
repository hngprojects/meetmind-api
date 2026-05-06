import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4

from app.models.user import User


# ── Helpers ──────────────────────────────────────────────────────────────────

def make_user(**kwargs) -> User:
    """Return a minimal mock User object."""
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


# ── Success ───────────────────────────────────────────────────────────────────

class TestSignupSuccess:
    @pytest.mark.anyio
    async def test_returns_201_on_valid_payload(self, client):
        user = make_user()
        with patch("app.services.auth.AuthService.create_user", new_callable=AsyncMock, return_value=user):
            response = await client.post(SIGNUP_URL, json=VALID_PAYLOAD)

        assert response.status_code == 201

    @pytest.mark.anyio
    async def test_response_body_shape(self, client):
        user = make_user()
        with patch("app.services.auth.AuthService.create_user", new_callable=AsyncMock, return_value=user):
            response = await client.post(SIGNUP_URL, json=VALID_PAYLOAD)

        body = response.json()
        assert body["status_code"] == 201
        assert body["message"] == "Account created successfully"
        assert "data" in body

    @pytest.mark.anyio
    async def test_response_data_contains_user_fields(self, client):
        user = make_user(email="john@example.com", name="John Doe")
        with patch("app.services.auth.AuthService.create_user", new_callable=AsyncMock, return_value=user):
            response = await client.post(SIGNUP_URL, json=VALID_PAYLOAD)

        data = response.json()["data"]
        assert data["email"] == "john@example.com"
        assert data["name"] == "John Doe"
        assert "id" in data

    @pytest.mark.anyio
    async def test_response_id_is_string(self, client):
        user = make_user()
        with patch("app.services.auth.AuthService.create_user", new_callable=AsyncMock, return_value=user):
            response = await client.post(SIGNUP_URL, json=VALID_PAYLOAD)

        assert isinstance(response.json()["data"]["id"], str)

    @pytest.mark.anyio
    async def test_password_not_returned_in_response(self, client):
        user = make_user()
        with patch("app.services.auth.AuthService.create_user", new_callable=AsyncMock, return_value=user):
            response = await client.post(SIGNUP_URL, json=VALID_PAYLOAD)

        body = response.json()
        assert "password" not in body.get("data", {})
        assert "password_hash" not in body.get("data", {})

    @pytest.mark.anyio
    async def test_name_with_leading_trailing_spaces_is_accepted(self, client):
        user = make_user(name="John Doe")
        payload = {**VALID_PAYLOAD, "name": "  John Doe  "}
        with patch("app.services.auth.AuthService.create_user", new_callable=AsyncMock, return_value=user):
            response = await client.post(SIGNUP_URL, json=payload)

        assert response.status_code == 201


# ── Duplicate email ────────────────────────────────────────────────────────────

class TestSignupDuplicateEmail:
    @pytest.mark.anyio
    async def test_returns_400_when_email_already_registered(self, client):
        from fastapi import HTTPException
        with patch(
            "app.services.auth.AuthService.create_user",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=400, detail="Email already registered"),
        ):
            response = await client.post(SIGNUP_URL, json=VALID_PAYLOAD)

        assert response.status_code == 400

    @pytest.mark.anyio
    async def test_error_body_on_duplicate_email(self, client):
        from fastapi import HTTPException
        with patch(
            "app.services.auth.AuthService.create_user",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=400, detail="Email already registered"),
        ):
            response = await client.post(SIGNUP_URL, json=VALID_PAYLOAD)

        body = response.json()
        assert body["status_code"] == 400
        assert "email" in body["message"].lower() or "registered" in body["message"].lower()


# ── Server error ──────────────────────────────────────────────────────────────

class TestSignupServerError:
    @pytest.mark.anyio
    async def test_returns_500_on_unexpected_exception(self, client):
        with patch(
            "app.services.auth.AuthService.create_user",
            new_callable=AsyncMock,
            side_effect=Exception("DB went boom"),
        ):
            response = await client.post(SIGNUP_URL, json=VALID_PAYLOAD)

        assert response.status_code == 500

    @pytest.mark.anyio
    async def test_error_body_on_server_error(self, client):
        with patch(
            "app.services.auth.AuthService.create_user",
            new_callable=AsyncMock,
            side_effect=Exception("DB went boom"),
        ):
            response = await client.post(SIGNUP_URL, json=VALID_PAYLOAD)

        body = response.json()
        assert body["status_code"] == 500
        assert "internal" in body["message"].lower()


# ── Input validation – name ────────────────────────────────────────────────────

class TestSignupNameValidation:
    @pytest.mark.anyio
    async def test_missing_name_returns_422(self, client):
        payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "name"}
        response = await client.post(SIGNUP_URL, json=payload)
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_whitespace_only_name_returns_422(self, client):
        response = await client.post(SIGNUP_URL, json={**VALID_PAYLOAD, "name": "   "})
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_empty_name_returns_422(self, client):
        response = await client.post(SIGNUP_URL, json={**VALID_PAYLOAD, "name": ""})
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_name_exceeding_max_length_returns_422(self, client):
        response = await client.post(SIGNUP_URL, json={**VALID_PAYLOAD, "name": "A" * 121})
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_name_with_html_tags_returns_422(self, client):
        response = await client.post(SIGNUP_URL, json={**VALID_PAYLOAD, "name": "<script>alert(1)</script>"})
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_name_at_max_length_is_accepted(self, client):
        user = make_user()
        with patch("app.services.auth.AuthService.create_user", new_callable=AsyncMock, return_value=user):
            response = await client.post(SIGNUP_URL, json={**VALID_PAYLOAD, "name": "A" * 120})
        assert response.status_code == 201


# ── Input validation – email ───────────────────────────────────────────────────

class TestSignupEmailValidation:
    @pytest.mark.anyio
    async def test_missing_email_returns_422(self, client):
        payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "email"}
        response = await client.post(SIGNUP_URL, json=payload)
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_invalid_email_format_returns_422(self, client):
        response = await client.post(SIGNUP_URL, json={**VALID_PAYLOAD, "email": "not-an-email"})
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_email_without_domain_returns_422(self, client):
        response = await client.post(SIGNUP_URL, json={**VALID_PAYLOAD, "email": "user@"})
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_email_without_at_symbol_returns_422(self, client):
        response = await client.post(SIGNUP_URL, json={**VALID_PAYLOAD, "email": "userexample.com"})
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
        response = await client.post(SIGNUP_URL, json={**VALID_PAYLOAD, "password": "Ab1"})
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_password_without_uppercase_returns_422(self, client):
        response = await client.post(SIGNUP_URL, json={**VALID_PAYLOAD, "password": "lowercase1"})
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_password_without_lowercase_returns_422(self, client):
        response = await client.post(SIGNUP_URL, json={**VALID_PAYLOAD, "password": "UPPERCASE1"})
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_password_without_digit_returns_422(self, client):
        response = await client.post(SIGNUP_URL, json={**VALID_PAYLOAD, "password": "NoDigitPass"})
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_password_at_min_length_is_accepted(self, client):
        user = make_user()
        with patch("app.services.auth.AuthService.create_user", new_callable=AsyncMock, return_value=user):
            response = await client.post(SIGNUP_URL, json={**VALID_PAYLOAD, "password": "Secure1!"})
        assert response.status_code == 201


# ── Validation error response shape ───────────────────────────────────────────

class TestSignupValidationErrorShape:
    @pytest.mark.anyio
    async def test_422_body_has_status_code_field(self, client):
        response = await client.post(SIGNUP_URL, json={**VALID_PAYLOAD, "email": "bad"})
        assert response.json()["status_code"] == 422

    @pytest.mark.anyio
    async def test_422_body_has_message_field(self, client):
        response = await client.post(SIGNUP_URL, json={**VALID_PAYLOAD, "email": "bad"})
        assert "message" in response.json()

    @pytest.mark.anyio
    async def test_422_message_references_invalid_field(self, client):
        response = await client.post(SIGNUP_URL, json={**VALID_PAYLOAD, "email": "bad"})
        assert "email" in response.json()["message"].lower()


# ── Empty / malformed request body ────────────────────────────────────────────

class TestSignupMalformedRequest:
    @pytest.mark.anyio
    async def test_empty_body_returns_422(self, client):
        response = await client.post(SIGNUP_URL, json={})
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_non_json_body_returns_422(self, client):
        response = await client.post(
            SIGNUP_URL,
            content="this is not json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422