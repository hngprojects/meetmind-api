import uuid

import pytest
from sqlalchemy import select

from app.models.integration import UserPlatformIntegration
from app.models.user import User, UserInterviewPreferences, UserMeetingPreferences
from app.services.auth import AuthService

BASE_URL = "/api/v1/onboarding"


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def create_user(db_session) -> User:
    user = User(name="Tester", email=f"u-{uuid.uuid4()}@example.com", is_verified=True)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


class TestOnboardingRole:
    @pytest.mark.anyio
    async def test_role_persists_all_fields(self, client, db_session):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        payload = {"companyName": "Acme", "role": "Recruiter", "hires": "1-10"}

        response = await client.post(
            f"{BASE_URL}/role", json=payload, headers=auth_header(token)
        )
        assert response.status_code == 200

        await db_session.refresh(user)
        assert user.company == "Acme"
        assert user.role == "Recruiter"
        assert user.hires == "1-10"

    @pytest.mark.anyio
    async def test_role_returns_422_when_required_field_missing(
        self, client, db_session
    ):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        response = await client.post(
            f"{BASE_URL}/role",
            json={"role": "Recruiter", "hires": "1-10"},
            headers=auth_header(token),
        )
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_role_returns_422_for_invalid_role(self, client, db_session):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        payload = {"companyName": "Acme", "role": "Invalid Role", "hires": "1-10"}
        response = await client.post(
            f"{BASE_URL}/role", json=payload, headers=auth_header(token)
        )
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_role_returns_401_without_token(self, client):
        response = await client.post(
            f"{BASE_URL}/role",
            json={"companyName": "Acme", "role": "Recruiter", "hires": "1-10"},
        )
        assert response.status_code == 401


class TestOnboardingPreferences:
    @pytest.mark.anyio
    async def test_preferences_success(self, client, db_session):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        payload = {
            "tone": "friendly",
            "preferences": {"dynamic": True, "autoRecord": False, "announce": True},
        }

        response = await client.post(
            f"{BASE_URL}/preferences", json=payload, headers=auth_header(token)
        )
        assert response.status_code == 200

        meeting_pref = (
            await db_session.execute(
                select(UserMeetingPreferences).where(
                    UserMeetingPreferences.user_id == user.id
                )
            )
        ).scalar_one()
        interview_pref = (
            await db_session.execute(
                select(UserInterviewPreferences).where(
                    UserInterviewPreferences.user_id == user.id
                )
            )
        ).scalar_one()
        assert meeting_pref.unlimited_transcripts is True
        assert meeting_pref.auto_record is False
        assert meeting_pref.announce is True
        assert interview_pref.tone == "friendly"

    @pytest.mark.anyio
    async def test_preferences_returns_422_when_preferences_missing(
        self, client, db_session
    ):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        response = await client.post(
            f"{BASE_URL}/preferences",
            json={"tone": "friendly"},
            headers=auth_header(token),
        )
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_preferences_returns_422_when_boolean_field_invalid(
        self, client, db_session
    ):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        response = await client.post(
            f"{BASE_URL}/preferences",
            json={
                "tone": "friendly",
                "preferences": {"dynamic": "yes", "autoRecord": True, "announce": True},
            },
            headers=auth_header(token),
        )
        assert response.status_code == 422


class TestOnboardingIntegrations:
    @pytest.mark.anyio
    @pytest.mark.parametrize("value", ["google", "zoom", None])
    async def test_integrations_success(self, client, db_session, value):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        response = await client.post(
            f"{BASE_URL}/integrations",
            json={"integrations": value},
            headers=auth_header(token),
        )
        assert response.status_code == 200

    @pytest.mark.anyio
    async def test_integrations_unsupported_value(self, client, db_session):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        response = await client.post(
            f"{BASE_URL}/integrations",
            json={"integrations": "slack"},
            headers=auth_header(token),
        )
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_integrations_401_without_token(self, client):
        response = await client.post(
            f"{BASE_URL}/integrations", json={"integrations": "google"}
        )
        assert response.status_code == 401


class TestOnboardingSubmission:
    @pytest.mark.anyio
    async def test_submission_marks_onboarding_completed(self, client, db_session):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)

        response = await client.post(
            f"{BASE_URL}/submission", headers=auth_header(token)
        )
        assert response.status_code == 200
        body = response.json()
        assert body["data"] == {"success": True, "onboardingCompleted": True}

        await db_session.refresh(user)
        assert user.onboarding_completed is True

    @pytest.mark.anyio
    async def test_submission_idempotent(self, client, db_session):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)

        first = await client.post(f"{BASE_URL}/submission", headers=auth_header(token))
        second = await client.post(f"{BASE_URL}/submission", headers=auth_header(token))
        assert first.status_code == 200
        assert second.status_code == 200

    @pytest.mark.anyio
    async def test_submission_401_without_token(self, client):
        response = await client.post(f"{BASE_URL}/submission")
        assert response.status_code == 401


@pytest.mark.anyio
async def test_full_four_step_happy_path(client, db_session):
    user = await create_user(db_session)
    token = await AuthService.create_access_token(user)
    headers = auth_header(token)

    assert (
        await client.post(
            f"{BASE_URL}/role",
            json={"companyName": "Acme", "role": "Recruiter", "hires": "1-10"},
            headers=headers,
        )
    ).status_code == 200
    assert (
        await client.post(
            f"{BASE_URL}/preferences",
            json={
                "tone": "friendly",
                "preferences": {"dynamic": True, "autoRecord": True, "announce": False},
            },
            headers=headers,
        )
    ).status_code == 200
    assert (
        await client.post(
            f"{BASE_URL}/integrations", json={"integrations": "google"}, headers=headers
        )
    ).status_code == 200
    assert (
        await client.post(f"{BASE_URL}/submission", headers=headers)
    ).status_code == 200

    me = await client.get("/api/v1/users/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["data"]["onboarding_completed"] is True

    rows = (
        (
            await db_session.execute(
                select(UserPlatformIntegration).where(
                    UserPlatformIntegration.user_id == user.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].platform == "google"
