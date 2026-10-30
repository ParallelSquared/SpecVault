"""Store paths relative to the lab share

Paths used to be stored exactly as the person who added the library typed
them, which meant the same file had as many spellings as there were ways to
reach it -- L:\\, \\\\PTI\\Lab, /Volumes/Lab, /mnt/lab -- and the unique
constraint on path could not see that they were one library. They are now
stored relative to the share; see app/share.py.

This rewrites the rows that were already there. A path that is not on the
share, or any path at all when no share is configured, is left exactly as it
was: app.share.resolve() still opens those, so nothing stops working, and
guessing at a translation would be worse than leaving it legible.

Revision ID: 3b69dad453b9
Revises: 722fc51941ab
Create Date: 2026-10-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app import share

revision: str = '3b69dad453b9'
down_revision: Union[str, Sequence[str], None] = '722fc51941ab'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# source_runs is deliberately not here: those name raw files that may sit on an
# instrument's own storage rather than the share, and are informational.
PATH_COLUMNS = ("path", "creation_log_path", "fasta_path")

_LIBRARIES = sa.table(
    "libraries",
    sa.column("id", sa.Integer),
    *[sa.column(name, sa.String) for name in PATH_COLUMNS],
)


def _rewrite(value, convert) -> object:
    """A path column's new value, or None when it should be left alone.

    fasta_path holds several paths joined by "; ", so each is converted on its
    own and the field is only rewritten when at least one of them changed.
    """
    if not value:
        return None
    parts = [part for part in value.split("; ") if part]
    rewritten = "; ".join(convert(part) or part for part in parts)
    return rewritten if rewritten != value else None


def _rows():
    return op.get_bind().execute(
        sa.select(_LIBRARIES.c.id, *[_LIBRARIES.c[name] for name in PATH_COLUMNS])
    ).mappings().all()


def _convert_every_path(convert) -> None:
    """Apply *convert* to every path column of every library."""
    connection = op.get_bind()
    for row in _rows():
        updates = {}
        for name in PATH_COLUMNS:
            rewritten = _rewrite(row[name], convert)
            if rewritten is not None:
                updates[name] = rewritten
        if updates:
            connection.execute(
                _LIBRARIES.update().where(_LIBRARIES.c.id == row["id"]).values(**updates)
            )


def _to_canonical(path: str):
    """The share-relative form of an absolute path, or None to leave it.

    Only absolute paths are converted. A path that is already relative is
    already canonical, and running it through to_canonical() again would
    strip a second prefix from it: a library genuinely stored in a folder
    called mnt/lab on the share canonicalises to "mnt/lab/foo.tsv", which
    matches the Linux mount and would lose its first two folders. The
    migration has to be safe to apply to a row twice, because downgrading
    and upgrading again does exactly that.
    """
    if not share.is_absolute(path):
        return None
    return share.to_canonical(path)


def upgrade() -> None:
    if not share.configured():
        # Refusing rather than passing quietly. This migration can only run
        # once: stamped as done against a server that had no share.json yet,
        # it converts nothing, is never tried again, and the catalog keeps
        # absolute paths forever -- which is the thing it exists to stop.
        # An empty catalog has nothing to lose, so a fresh install is fine.
        if any(row[name] for row in _rows() for name in PATH_COLUMNS):
            raise RuntimeError(
                "This catalog has paths to convert, but no lab share is configured, "
                "so there is nothing to convert them against. Put backend/share.json "
                "in place (or point SHARE_CONFIG at it) and start again. If this "
                "catalog is deliberately not on a share, its paths are already right: "
                "skip this migration with `alembic stamp 3b69dad453b9`."
            )
        return
    _convert_every_path(_to_canonical)


def downgrade() -> None:
    """Back to absolute paths, written the way this server reaches the share.

    Not the spelling each was added with -- that was never recorded, and is
    the thing this migration exists to stop mattering.
    """
    if not share.configured():
        return
    _convert_every_path(
        lambda path: share.to_local(path) if not share.is_absolute(path) else None
    )
