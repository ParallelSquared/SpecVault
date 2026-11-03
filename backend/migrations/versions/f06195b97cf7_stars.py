"""Stars

A new table and nothing else, so no rebuild of anything that holds data.

Revision ID: f06195b97cf7
Revises: 89558a4caadd
Create Date: 2026-11-03 16:30:31.279771

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f06195b97cf7'
down_revision: Union[str, Sequence[str], None] = '89558a4caadd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('library_stars',
    sa.Column('library_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('starred_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['library_id'], ['libraries.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('library_id', 'name')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('library_stars')
