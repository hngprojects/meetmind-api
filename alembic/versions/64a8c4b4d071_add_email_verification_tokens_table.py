"""add email verification tokens table

Revision ID: 64a8c4b4d071
Revises: cacd5554ba5a
Create Date: 2026-05-06 18:45:39.840324

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '64a8c4b4d071'
down_revision: Union[str, None] = 'cacd5554ba5a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
    "email_verification_tokens",
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("token_hash", sa.String(length=255), nullable=False),
    sa.Column("expires_at", sa.DateTime(), nullable=False),
    sa.Column("used_at", sa.DateTime(), nullable=True),
    sa.Column(
        "created_at",
        sa.DateTime(),
        server_default=sa.func.now(),
        nullable=True,
    ),
    sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )

    # Optional but recommended index
    op.create_index(
        "ix_email_verification_token_hash",
        "email_verification_tokens",
        ["token_hash"],
        unique=False,
    )



def downgrade() -> None:
    op.drop_index("ix_email_verification_token_hash", table_name="email_verification_tokens")
    op.drop_table("email_verification_tokens")