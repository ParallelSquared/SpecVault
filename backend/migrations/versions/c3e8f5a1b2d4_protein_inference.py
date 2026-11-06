"""Protein inference

Revision ID: c3e8f5a1b2d4
Revises: b7c41e2a9d10
Create Date: 2026-11-06 11:00:00.000000

Plain add_column, both ways: no batch rebuild of `libraries`, whose DROP
would cascade into library_paths. SQLite (3.35 on) drops an unindexed column
natively.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3e8f5a1b2d4'
down_revision: Union[str, Sequence[str], None] = 'b7c41e2a9d10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. Libraries already catalogued have nothing for it."""
    op.add_column('libraries', sa.Column('protein_inference', sa.Boolean(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('libraries', 'protein_inference')
