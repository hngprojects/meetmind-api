"""merge all heads

Revision ID: 5b25f8695307
Revises: 64a8c4b4d071, 864df66fbeb7, 8d114ef61fcc
Create Date: 2026-05-07 11:13:52.251661

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '5b25f8695307'
down_revision: Union[str, None] = ('64a8c4b4d071', '864df66fbeb7', '8d114ef61fcc')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
