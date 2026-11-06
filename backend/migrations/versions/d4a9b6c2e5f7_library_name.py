"""Library name

Revision ID: d4a9b6c2e5f7
Revises: c3e8f5a1b2d4
Create Date: 2026-11-06 16:30:00.000000

Plain add_column, both ways: no batch rebuild of `libraries`, whose DROP
would cascade into library_paths.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4a9b6c2e5f7'
down_revision: Union[str, Sequence[str], None] = 'c3e8f5a1b2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. Libraries already catalogued have none, and show
    their folder and file name until someone gives them one."""
    op.add_column('libraries', sa.Column('name', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('libraries', 'name')
