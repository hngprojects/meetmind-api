"""add started_at to interviews

Revision ID: 26db59e0e822
Revises: 4ebdeb2c43d6
Create Date: 2026-05-29 15:54:39.980396

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '26db59e0e822'
down_revision: Union[str, None] = '4ebdeb2c43d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    
    # Check if 'started_at' already exists before adding
    interviews_cols = [col['name'] for col in inspector.get_columns('interviews')]
    if 'started_at' not in interviews_cols:
        op.add_column('interviews', sa.Column('started_at', sa.DateTime(timezone=True), nullable=True))
    
    # Check if 'is_verified' exists before altering
    users_cols = [col['name'] for col in inspector.get_columns('users')]
    if 'is_verified' in users_cols:
        op.alter_column('users', 'is_verified',
                   existing_type=sa.BOOLEAN(),
                   nullable=True,
                   existing_server_default=sa.text('false'))
    # ### end Alembic commands ###


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    
    users_cols = [col['name'] for col in inspector.get_columns('users')]
    if 'is_verified' in users_cols:
        op.alter_column('users', 'is_verified',
                   existing_type=sa.BOOLEAN(),
                   nullable=False,
                   existing_server_default=sa.text('false'))
    
    interviews_cols = [col['name'] for col in inspector.get_columns('interviews')]
    if 'started_at' in interviews_cols:
        op.drop_column('interviews', 'started_at')
    # ### end Alembic commands ###
