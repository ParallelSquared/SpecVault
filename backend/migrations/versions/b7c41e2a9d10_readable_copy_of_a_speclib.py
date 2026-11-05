"""Readable copy of a .speclib

Revision ID: b7c41e2a9d10
Revises: f06195b97cf7
Create Date: 2026-11-05 10:00:00.000000

Plain add_column, both ways: no batch rebuild of `libraries`, whose DROP
would cascade into library_paths. SQLite drops a column natively (3.35 on)
once nothing indexes it, so the downgrade drops the index first.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7c41e2a9d10'
down_revision: Union[str, Sequence[str], None] = 'f06195b97cf7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('libraries', sa.Column('readable_copy_path', sa.String(), nullable=True))
    op.add_column('libraries', sa.Column('readable_copy_hash', sa.String(), nullable=True))
    op.create_index(op.f('ix_libraries_readable_copy_hash'), 'libraries', ['readable_copy_hash'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_libraries_readable_copy_hash'), table_name='libraries')
    op.drop_column('libraries', 'readable_copy_hash')
    op.drop_column('libraries', 'readable_copy_path')
