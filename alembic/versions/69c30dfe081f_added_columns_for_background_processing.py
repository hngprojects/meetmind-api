"""added columns for background processing

Revision ID: 69c30dfe081f
Revises: 65b241731b58
Create Date: 2026-05-19 06:24:12.797134

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '69c30dfe081f'
down_revision: Union[str, None] = '65b241731b58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DOCUMENT_STATUS_ENUM = postgresql.ENUM(
    "pending",
    "processing",
    "completed",
    "failed",
    name="document_status",
)


def upgrade() -> None:
    DOCUMENT_STATUS_ENUM.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "candidate_documents",
        sa.Column(
            "status",
            DOCUMENT_STATUS_ENUM,
            nullable=False,
            server_default="pending",
        ),
    )

    op.add_column(
        "candidate_documents",
        sa.Column(
            "error_message",
            sa.Text(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("candidate_documents", "error_message")
    op.drop_column("candidate_documents", "status")

    DOCUMENT_STATUS_ENUM.drop(op.get_bind(), checkfirst=True)
