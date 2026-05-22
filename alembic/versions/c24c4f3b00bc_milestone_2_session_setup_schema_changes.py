"""milestone 2 session setup schema changes

Revision ID: c24c4f3b00bc
Revises: 4220c2a1fc6a
Create Date: 2026-05-21 02:42:53.023367

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c24c4f3b00bc'
down_revision: Union[str, None] = '4220c2a1fc6a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('interviews', 'candidate_id', nullable=True)
    op.add_column('interviews', sa.Column('call_link', sa.Text(), nullable=True))
    op.add_column('interviews', sa.Column('participation_mode', sa.String(20), nullable=True))
    op.add_column('interview_summaries', sa.Column('key_skills', sa.Text(), nullable=True))

def downgrade() -> None:
    op.drop_column('interview_summaries', 'key_skills')
    op.drop_column('interviews', 'participation_mode')
    op.drop_column('interviews', 'call_link')
    op.alter_column('interviews', 'candidate_id', nullable=False)