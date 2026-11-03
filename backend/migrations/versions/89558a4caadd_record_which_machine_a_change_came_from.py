"""Record which machine a change came from

Revision ID: 89558a4caadd
Revises: 0a1edf5db586
Create Date: 2026-11-03 15:39:53.854511

A plain add_column: native in SQLite, so no table rebuild. The downgrade does
rebuild library_versions to drop the column, which is safe where rebuilding
`libraries` was not -- nothing references library_versions, so its DROP
cascades into nothing.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '89558a4caadd'
down_revision: Union[str, Sequence[str], None] = '0a1edf5db586'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. Rows recorded before this have no machine."""
    op.add_column('library_versions', sa.Column('changed_from', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('library_versions', schema=None) as batch_op:
        batch_op.drop_column('changed_from')
