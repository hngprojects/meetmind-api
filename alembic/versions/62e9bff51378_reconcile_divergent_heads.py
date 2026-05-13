"""reconcile divergent heads

Revision ID: 62e9bff51378
Revises: 7047971f0a0a, ed6aad565b56
Create Date: 2026-05-13 19:21:48.894394

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '62e9bff51378'
down_revision: Union[str, None] = ('7047971f0a0a', 'ed6aad565b56')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
