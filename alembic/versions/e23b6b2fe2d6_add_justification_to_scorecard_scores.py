"""add justification column to scorecard_scores

Revision ID: e23b6b2fe2d6
Revises: 2fc0df3741d1
Create Date: 2026-06-05 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e23b6b2fe2d6'
down_revision: Union[str, None] = '2fc0df3741d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('scorecard_scores', sa.Column('justification', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('scorecard_scores', 'justification')
