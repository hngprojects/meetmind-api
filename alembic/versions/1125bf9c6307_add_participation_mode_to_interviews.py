"""add participation_mode to interviews

Revision ID: 1125bf9c6307
Revises: c24c4f3b00bc
Create Date: 2026-05-19 07:22:40.249473

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '1125bf9c6307'
down_revision: Union[str, None] = 'c24c4f3b00bc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('interviews', 'participation_mode',
                    existing_type=sa.String(20),
                    server_default='standard')
    op.execute("UPDATE interviews SET participation_mode = 'standard' WHERE participation_mode IS NULL")
    op.alter_column('interviews', 'participation_mode',
                    existing_type=sa.String(20),
                    nullable=False)


def downgrade() -> None:
    op.alter_column('interviews', 'participation_mode',
                    existing_type=sa.String(20),
                    nullable=True)
    op.alter_column('interviews', 'participation_mode',
                    existing_type=sa.String(20),
                    server_default=None)
