"""Record a history of changes

Revision ID: 0a1edf5db586
Revises: 9ae6e9451e73
Create Date: 2026-11-03 11:08:21.626218

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0a1edf5db586'
down_revision: Union[str, Sequence[str], None] = '9ae6e9451e73'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Purely additive: a new table, and nothing touched on `libraries`, so none
    of the rebuild-and-cascade care the earlier migrations need applies here.
    Catalogs that already hold libraries start with no history, and gain one
    from their next change onwards.
    """
    op.create_table(
        'library_versions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('library_id', sa.Integer(), nullable=False),
        sa.Column('recorded_at', sa.DateTime(timezone=True),
                  server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('changed_by', sa.String(), nullable=True),
        sa.Column('event', sa.String(), nullable=False),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(['library_id'], ['libraries.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_library_versions_id'), 'library_versions', ['id'], unique=False)
    op.create_index(op.f('ix_library_versions_library_id'), 'library_versions',
                    ['library_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema. The history is the only thing here, so it goes."""
    op.drop_index(op.f('ix_library_versions_library_id'), table_name='library_versions')
    op.drop_index(op.f('ix_library_versions_id'), table_name='library_versions')
    op.drop_table('library_versions')
