import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.notification import Notification
from app.services.notification_service import NotificationService, time_display


class TestNotificationService:
    @pytest.mark.anyio
    async def test_create_persists_notification(self, db_session):
        user_id = uuid.uuid4()
        notif = await NotificationService.create(
            db=db_session,
            user_id=user_id,
            type="report",
            title="Test Title",
            description="Test description",
            action_label="View",
            action_url="/test",
        )
        assert notif.id is not None
        assert notif.user_id == user_id
        assert notif.type == "report"
        assert notif.title == "Test Title"
        assert notif.description == "Test description"
        assert notif.action_label == "View"
        assert notif.action_url == "/test"
        assert notif.is_read is False
        assert notif.deleted_at is None

    @pytest.mark.anyio
    async def test_list_for_user_returns_newest_first(self, db_session):
        now = datetime.now(timezone.utc)
        user_id = uuid.uuid4()
        n1 = await NotificationService.create(
            db=db_session,
            user_id=user_id,
            type="report",
            title="Older",
        )
        n1.created_at = now - timedelta(seconds=5)
        n2 = await NotificationService.create(
            db=db_session,
            user_id=user_id,
            type="report",
            title="Newer",
        )
        n2.created_at = now
        await db_session.commit()

        notifs, total = await NotificationService.list_for_user(
            db=db_session,
            user_id=user_id,
        )
        assert total == 2
        assert [n.id for n in notifs] == [n2.id, n1.id]

    @pytest.mark.anyio
    async def test_list_for_user_excludes_soft_deleted(self, db_session):
        user_id = uuid.uuid4()
        await NotificationService.create(
            db=db_session,
            user_id=user_id,
            type="report",
            title="Active",
        )
        deleted = await NotificationService.create(
            db=db_session,
            user_id=user_id,
            type="report",
            title="Deleted",
        )
        deleted.deleted_at = datetime.now(timezone.utc)
        await db_session.commit()

        notifs, total = await NotificationService.list_for_user(
            db=db_session,
            user_id=user_id,
        )
        assert total == 1
        assert notifs[0].title == "Active"

    @pytest.mark.anyio
    async def test_filter_unread_returns_only_unread(self, db_session):
        user_id = uuid.uuid4()
        read = await NotificationService.create(
            db=db_session,
            user_id=user_id,
            type="report",
            title="Read",
        )
        read.is_read = True
        unread = await NotificationService.create(
            db=db_session,
            user_id=user_id,
            type="report",
            title="Unread",
        )
        await db_session.commit()

        notifs, total = await NotificationService.list_for_user(
            db=db_session,
            user_id=user_id,
            filter="unread",
        )
        assert total == 1
        assert notifs[0].title == "Unread"

    @pytest.mark.anyio
    async def test_mark_read_sets_is_read_true(self, db_session):
        user_id = uuid.uuid4()
        notif = await NotificationService.create(
            db=db_session,
            user_id=user_id,
            type="report",
            title="Test",
        )
        updated = await NotificationService.mark_read(
            db=db_session,
            notification_id=notif.id,
            user_id=user_id,
        )
        assert updated.is_read is True

    @pytest.mark.anyio
    async def test_mark_all_read_marks_all_as_read(self, db_session):
        user_id = uuid.uuid4()
        await NotificationService.create(
            db=db_session,
            user_id=user_id,
            type="report",
            title="A",
        )
        await NotificationService.create(
            db=db_session,
            user_id=user_id,
            type="report",
            title="B",
        )
        await NotificationService.mark_all_read(db=db_session, user_id=user_id)

        from sqlalchemy import select

        result = await db_session.execute(
            select(Notification).where(Notification.user_id == user_id)
        )
        all_notifs = result.scalars().all()
        assert all(n.is_read for n in all_notifs)

    @pytest.mark.anyio
    async def test_soft_delete_all_sets_deleted_at_does_not_delete(self, db_session):
        user_id = uuid.uuid4()
        await NotificationService.create(
            db=db_session,
            user_id=user_id,
            type="report",
            title="A",
        )
        await NotificationService.create(
            db=db_session,
            user_id=user_id,
            type="report",
            title="B",
        )
        await NotificationService.soft_delete_all(db=db_session, user_id=user_id)

        from sqlalchemy import select

        result = await db_session.execute(
            select(Notification).where(Notification.user_id == user_id)
        )
        all_notifs = result.scalars().all()
        assert len(all_notifs) == 2
        assert all(n.deleted_at is not None for n in all_notifs)


class TestTimeDisplay:
    def test_just_now(self):
        now = datetime.now(timezone.utc)
        dt = now - timedelta(seconds=10)
        assert time_display(dt, now=now) == "Just now"

    def test_minutes_ago(self):
        now = datetime.now(timezone.utc)
        dt = now - timedelta(minutes=5)
        assert time_display(dt, now=now) == "5 min ago"

    def test_hours_ago(self):
        now = datetime(2025, 6, 15, 15, 0, 0, tzinfo=timezone.utc)  # 3pm
        dt = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)  # noon same day
        assert time_display(dt, now=now) == "3 hours ago"

    def test_yesterday(self):
        now = datetime.now(timezone.utc)
        dt = (now - timedelta(days=1)).replace(hour=12, minute=0, second=0)
        assert time_display(dt, now=now) == "Yesterday"

    def test_older_date_format(self):
        now = datetime.now(timezone.utc)
        dt = now - timedelta(days=5)
        expected = dt.strftime("%a %b %d").lstrip("0").replace("  ", " ")
        assert time_display(dt, now=now) == expected
