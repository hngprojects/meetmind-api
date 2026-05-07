"""add refresh_token_hash to active_sessions

Revision ID: a8cbb47717b3
Revises: cacd5554ba5a
Create Date: 2026-05-06 19:37:58.824448

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a8cbb47717b3'
down_revision: Union[str, None] = 'cacd5554ba5a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('active_sessions', sa.Column('refresh_token_hash', sa.String(length=255), nullable=False))
    op.create_index(op.f('ix_active_sessions_refresh_token_hash'), 'active_sessions', ['refresh_token_hash'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_active_sessions_refresh_token_hash'), table_name='active_sessions')
    op.drop_column('active_sessions', 'refresh_token_hash')
