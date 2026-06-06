import uuid

from app.models.base import Base
from app.models.notification import Notification


class TestNotificationModel:
    def test_table_exists(self):
        assert "notifications" in Base.metadata.tables

    def test_has_expected_columns(self):
        table = Base.metadata.tables["notifications"]
        cols = {c.name for c in table.columns}
        expected = {
            "id",
            "user_id",
            "type",
            "title",
            "description",
            "is_read",
            "action_label",
            "action_url",
            "created_at",
            "updated_at",
            "deleted_at",
        }
        assert expected.issubset(cols)

    def test_user_id_foreign_key(self):
        table = Base.metadata.tables["notifications"]
        fk_targets = {fk.column.table.name for fk in table.foreign_keys}
        assert "users" in fk_targets

    async def test_is_read_defaults_to_false(self, db_session):
        notif = Notification(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            type="report",
            title="Test",
        )
        db_session.add(notif)
        await db_session.commit()
        await db_session.refresh(notif)
        assert notif.is_read is False

    async def test_deleted_at_defaults_to_none(self, db_session):
        notif = Notification(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            type="report",
            title="Test",
        )
        db_session.add(notif)
        await db_session.commit()
        await db_session.refresh(notif)
        assert notif.deleted_at is None
