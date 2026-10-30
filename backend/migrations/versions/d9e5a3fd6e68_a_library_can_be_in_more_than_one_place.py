"""A library can be in more than one place

A library's file is often copied -- kept beside the runs it came from and
again in a shared folder -- and those copies are one library, not several.
The single path column becomes a table, so an entry can list every place its
file is, and a path still belongs to exactly one entry.

Autogenerate wrote this as "create the table, drop the column" and would have
thrown every path in the catalog away. The rows are moved across first.

Revision ID: d9e5a3fd6e68
Revises: 3b69dad453b9
Create Date: 2026-10-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'd9e5a3fd6e68'
down_revision: Union[str, Sequence[str], None] = '3b69dad453b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Read the paths out before touching anything. SQLite cannot drop a
    # column: batch_alter_table builds a new libraries table, copies the rows
    # over, DROPs the old one and renames. With foreign keys enforced, that
    # DROP cascades into any table referencing libraries -- so writing the
    # paths into library_paths first and dropping the column afterwards
    # deletes every row just written. Nothing references libraries while the
    # column is dropped, so there is nothing for the drop to cascade into.
    connection = op.get_bind()
    existing = connection.execute(
        sa.text("SELECT id, path FROM libraries WHERE path IS NOT NULL ORDER BY id")
    ).fetchall()

    with op.batch_alter_table('libraries', schema=None) as batch_op:
        batch_op.drop_column('path')

    op.create_table(
        'library_paths',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('library_id', sa.Integer(), nullable=False),
        sa.Column('path', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['library_id'], ['libraries.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('path'),
    )
    with op.batch_alter_table('library_paths', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_library_paths_id'), ['id'], unique=False)
        batch_op.create_index(
            batch_op.f('ix_library_paths_library_id'), ['library_id'], unique=False
        )

    # Every library's path becomes its first -- and so far only -- place.
    if existing:
        connection.execute(
            sa.text("INSERT INTO library_paths (library_id, path) VALUES (:id, :path)"),
            [{"id": row.id, "path": row.path} for row in existing],
        )


def downgrade() -> None:
    """Back to one path per library.

    A library recorded in several places keeps the first and loses the rest:
    there is nowhere in the old shape to put them. Nothing else is lost.
    """
    # Read out and drop library_paths before rebuilding libraries, for the
    # same reason the upgrade defers creating it: rebuilding libraries drops
    # the old table, and with foreign keys enforced that cascades into
    # anything pointing at it.
    connection = op.get_bind()
    first = {
        row.library_id: row.path
        for row in connection.execute(sa.text(
            "SELECT library_id, path FROM library_paths"
            " WHERE id IN (SELECT MIN(id) FROM library_paths GROUP BY library_id)"
        )).fetchall()
    }

    with op.batch_alter_table('library_paths', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_library_paths_library_id'))
        batch_op.drop_index(batch_op.f('ix_library_paths_id'))
    op.drop_table('library_paths')

    # Added nullable so the existing rows can be filled in before the column
    # is made NOT NULL -- adding it NOT NULL outright fails on any catalog
    # that has libraries in it, which is every catalog this would run on.
    with op.batch_alter_table('libraries', schema=None) as batch_op:
        batch_op.add_column(sa.Column('path', sa.VARCHAR(), nullable=True))

    for library_id, path in first.items():
        connection.execute(
            sa.text("UPDATE libraries SET path = :path WHERE id = :id"),
            {"path": path, "id": library_id},
        )
    # A library with no path at all cannot exist in the old shape. There
    # should be none; dropping any there are keeps the NOT NULL below honest.
    op.execute("DELETE FROM libraries WHERE path IS NULL")

    with op.batch_alter_table('libraries', schema=None) as batch_op:
        batch_op.alter_column('path', existing_type=sa.VARCHAR(), nullable=False)
        batch_op.create_unique_constraint('uq_libraries_path', ['path'])
