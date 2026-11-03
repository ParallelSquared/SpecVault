"""Soft delete libraries

Revision ID: 9ae6e9451e73
Revises: d9e5a3fd6e68
Create Date: 2026-11-02 10:51:25.584916

Deliberately not `batch_alter_table`. Batch mode rebuilds the table --
create, copy, DROP, rename -- and `library_paths.library_id` is ON DELETE
CASCADE, so with foreign keys on (which the app turns on) that DROP takes
every path with it. Adding a column and an index are both native statements
in SQLite, so neither needs the rebuild autogenerate reaches for.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9ae6e9451e73'
down_revision: Union[str, Sequence[str], None] = 'd9e5a3fd6e68'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('libraries', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f('ix_libraries_deleted_at'), 'libraries', ['deleted_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema.

    Dropping a column is the one thing SQLite cannot do without the rebuild,
    so the cascade above is unavoidable here: the paths are read out first and
    put back after. Going back also means deleted entries return to the
    catalog, since nothing is left to mark them deleted.
    """
    bind = op.get_bind()
    saved = [
        dict(row._mapping)
        for row in bind.execute(sa.text(
            "SELECT id, library_id, path FROM library_paths ORDER BY id"))
    ]

    op.drop_index(op.f('ix_libraries_deleted_at'), table_name='libraries')
    with op.batch_alter_table('libraries', schema=None) as batch_op:
        batch_op.drop_column('deleted_at')

    # OR IGNORE because whether the cascade fired depends on whether foreign
    # keys are on for this connection: with them off the rows never left.
    if saved:
        bind.execute(
            sa.text("INSERT OR IGNORE INTO library_paths (id, library_id, path) "
                    "VALUES (:id, :library_id, :path)"),
            saved,
        )
