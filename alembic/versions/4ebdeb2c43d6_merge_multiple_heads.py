"""merge multiple heads

Revision ID: 4ebdeb2c43d6
Revises: 7061d9a99af7, ba520220332d
Create Date: 2026-05-29 05:19:36.555599

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '4ebdeb2c43d6'
down_revision: Union[str, None] = ('7061d9a99af7', 'ba520220332d')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
