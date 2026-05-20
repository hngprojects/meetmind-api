"""added columns for background processing

Revision ID: 4484271ac63a
Revises: 65b241731b58
Create Date: 2026-05-19 12:52:57.364759
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4484271ac63a"
down_revision: Union[str, None] = "65b241731b58"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


document_status_enum = sa.Enum(
    "pending",
    "processing",
    "completed",
    "failed",
    name="document_status",
)


def upgrade() -> None:
    # Explicitly create enum type in Postgres
    document_status_enum.create(op.get_bind(), checkfirst=True)

    # Add processing status column
    op.add_column(
        "candidate_documents",
        sa.Column(
            "status",
            document_status_enum,
            nullable=False,
            server_default="pending",
        ),
    )

    # Add optional processing error field
    op.add_column(
        "candidate_documents",
        sa.Column(
            "error_message",
            sa.Text(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    # Drop columns first
    op.drop_column("candidate_documents", "error_message")
    op.drop_column("candidate_documents", "status")

    # Explicitly drop enum type
    document_status_enum.drop(
        op.get_bind(),
        checkfirst=True,
    )
