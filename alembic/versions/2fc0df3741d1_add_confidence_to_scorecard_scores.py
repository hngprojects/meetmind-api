"""add confidence column to scorecard_scores

Revision ID: 2fc0df3741d1
Revises: b32f66cb0043
Create Date: 2026-06-05 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '2fc0df3741d1'
down_revision: Union[str, None] = 'b32f66cb0043'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('scorecard_scores', sa.Column('confidence', sa.Integer(), nullable=True, server_default='0'))
    op.alter_column('scorecard_scores', 'confidence', server_default=None)


def downgrade() -> None:
    op.drop_column('scorecard_scores', 'confidence')
