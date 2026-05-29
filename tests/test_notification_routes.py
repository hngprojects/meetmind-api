import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.models.notification import Notification
from app.models.user import User
from app.services.notification_service import NotificationService


class TestNotificationsRoutes:

    async def _create_user(self, db_session) -> User:
        user = User(
            id=uuid.uuid4(),
            email=f"{uuid.uuid4()}@test.com",
            is_verified=True,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        return user

    async def _auth_header(self, user: User) -> dict:
        from app.services.auth import AuthService
        token = await AuthService.create_access_token(user)
        return {"Authorization": f"Bearer {token}"}

    @pytest.mark.anyio
    async def test_get_returns_list_with_unread_count(
        self, client: AsyncClient, db_session,
    ):
        user = await self._create_user(db_session)
        now = datetime.now(timezone.utc)
        for i in range(3):
            n = await NotificationService.create(
                db=db_session, user_id=user.id, type="report", title=f"N{i}",
            )
            n.created_at = now - timedelta(seconds=i)
            n.is_read = True
        n1 = await NotificationService.create(
            db=db_session, user_id=user.id, type="report", title="Unread",
        )
        n1.is_read = False
        await db_session.commit()

        headers = await self._auth_header(user)
        resp = await client.get("/api/v1/notifications", headers=headers)

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data["notifications"]) == 4
        assert data["unread_count"] == 1

    @pytest.mark.anyio
    async def test_get_filter_unread_returns_only_unread(
        self, client: AsyncClient, db_session,
    ):
        user = await self._create_user(db_session)
        r = await NotificationService.create(
            db=db_session, user_id=user.id, type="report", title="Read",
        )
        r.is_read = True
        u = await NotificationService.create(
            db=db_session, user_id=user.id, type="report", title="Unread",
        )
        u.is_read = False
        await db_session.commit()

        headers = await self._auth_header(user)
        resp = await client.get(
            "/api/v1/notifications?filter=unread", headers=headers,
        )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data["notifications"]) == 1
        assert data["notifications"][0]["title"] == "Unread"
        assert data["unread_count"] == 1

    @pytest.mark.anyio
    async def test_patch_mark_all_read_marks_all(
        self, client: AsyncClient, db_session,
    ):
        user = await self._create_user(db_session)
        for _ in range(3):
            await NotificationService.create(
                db=db_session, user_id=user.id, type="report", title="N",
            )

        headers = await self._auth_header(user)
        resp = await client.patch(
            "/api/v1/notifications/mark-all-read", headers=headers,
        )

        assert resp.status_code == 200

        from sqlalchemy import select
        result = await db_session.execute(
            select(Notification).where(Notification.user_id == user.id)
        )
        assert all(n.is_read for n in result.scalars().all())

    @pytest.mark.anyio
    async def test_patch_id_read_marks_single(
        self, client: AsyncClient, db_session,
    ):
        user = await self._create_user(db_session)
        notif = await NotificationService.create(
            db=db_session, user_id=user.id, type="report", title="Test",
        )

        headers = await self._auth_header(user)
        resp = await client.patch(
            f"/api/v1/notifications/{notif.id}/read", headers=headers,
        )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["is_read"] is True

    @pytest.mark.anyio
    async def test_patch_id_read_returns_404_for_other_users_notification(
        self, client: AsyncClient, db_session,
    ):
        owner = await self._create_user(db_session)
        notif = await NotificationService.create(
            db=db_session, user_id=owner.id, type="report", title="Mine",
        )
        other = await self._create_user(db_session)

        headers = await self._auth_header(other)
        resp = await client.patch(
            f"/api/v1/notifications/{notif.id}/read", headers=headers,
        )

        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_delete_clears_all_soft_delete(
        self, client: AsyncClient, db_session,
    ):
        user = await self._create_user(db_session)
        for _ in range(2):
            await NotificationService.create(
                db=db_session, user_id=user.id, type="report", title="N",
            )

        headers = await self._auth_header(user)
        resp = await client.delete("/api/v1/notifications", headers=headers)

        assert resp.status_code == 200

        notifs, total = await NotificationService.list_for_user(
            db=db_session, user_id=user.id,
        )
        assert total == 0

    @pytest.mark.anyio
    async def test_all_endpoints_return_401_without_token(
        self, client: AsyncClient,
    ):
        resp = await client.get("/api/v1/notifications")
        assert resp.status_code == 401

        resp = await client.patch("/api/v1/notifications/mark-all-read")
        assert resp.status_code == 401

        resp = await client.patch(
            f"/api/v1/notifications/{uuid.uuid4()}/read",
        )
        assert resp.status_code == 401

        resp = await client.delete("/api/v1/notifications")
        assert resp.status_code == 401