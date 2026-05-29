"""merge multiple heads

Revision ID: ba520220332d
Revises: a1df2ff87e17, e797dcd4433c
Create Date: 2026-05-29 04:16:23.181127

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'ba520220332d'
down_revision: Union[str, None] = ('a1df2ff87e17', 'e797dcd4433c')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
