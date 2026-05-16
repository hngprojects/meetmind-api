import uuid

import pytest
from httpx import AsyncClient

SIGNUP_URL = "/api/v1/auth/signup"


def unique_user() -> dict:
    suffix = uuid.uuid4().hex[:8]
    return {
        "name": "Onboard Tester",
        "email": f"onboard_{suffix}@example.com",
        "password": "SecurePass1!",
    }


async def signup_and_get_token(client: AsyncClient) -> str:
    response = await client.post(SIGNUP_URL, json=unique_user())
    assert response.status_code == 201
    return response.json()["data"]["access_token"]


@pytest.mark.anyio
async def test_onboarding_role_and_preferences(client: AsyncClient):
    token = await signup_and_get_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    role_res = await client.post(
        "/api/v1/onboarding/role", json={"role": "Recruiter"}, headers=headers
    )
    assert role_res.status_code == 200

    pref_res = await client.post(
        "/api/v1/onboarding/preferences",
        json={"join_condition": "all_calls", "send_recap_to": "me"},
        headers=headers,
    )
    assert pref_res.status_code == 200


@pytest.mark.anyio
async def test_onboarding_requires_auth(client: AsyncClient):
    response = await client.post("/api/v1/onboarding/role", json={"role": "Recruiter"})
    assert response.status_code == 401


@pytest.mark.anyio
async def test_onboarding_trial_activation(client: AsyncClient):
    token = await signup_and_get_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.post(
        "/api/v1/onboarding/trial", json={"decision": "accept"}, headers=headers
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["is_active"] is True
    assert data["ends_at"] is not None


@pytest.mark.anyio
async def test_onboarding_invalid_role_422(client: AsyncClient):
    token = await signup_and_get_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.post(
        "/api/v1/onboarding/role", json={"role": "Invalid"}, headers=headers
    )
    assert response.status_code == 422
