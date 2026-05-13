"""merge multiple migration heads

Revision ID: c6ef36577539
Revises: 480a265e5923, 90aeb7c687d7
Create Date: 2026-05-13 16:36:54.675099

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c6ef36577539'
down_revision: Union[str, None] = ('480a265e5923', '90aeb7c687d7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
