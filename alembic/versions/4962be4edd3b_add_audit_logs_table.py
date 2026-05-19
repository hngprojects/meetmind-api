"""add audit_logs table

Revision ID: 4962be4edd3b
Revises: 709ce6b18dc8
Create Date: 2026-05-19 14:46:57.166298

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "4962be4edd3b"
down_revision: Union[str, None] = "709ce6b18dc8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("interview_id", sa.UUID(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_table("audit_logs")
