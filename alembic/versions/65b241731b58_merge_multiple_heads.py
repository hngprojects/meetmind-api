"""merge multiple heads

Revision ID: 65b241731b58
Revises: 182e01c9ede0, d1fe0e57f2a0
Create Date: 2026-05-18 20:58:58.851734

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '65b241731b58'
down_revision: Union[str, None] = ('182e01c9ede0', 'd1fe0e57f2a0')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
