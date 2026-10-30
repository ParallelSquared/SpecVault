"""Alembic's entry point, wired to the app rather than to alembic.ini.

The database address is whatever the app itself would use -- app/database.py
reads DATABASE_URL from the environment or .env -- so a migration can never run
against a different database than the one the server is about to open. That is
also why alembic.ini carries no sqlalchemy.url: there is one answer to "which
database", and it does not live here.

Importing app.models is what registers every table on Base.metadata; without it
autogenerate sees an empty schema and happily writes a migration dropping
everything.
"""
from logging.config import fileConfig

from alembic import context

from app import models  # noqa: F401  -- registers the tables on Base.metadata
from app.database import DATABASE_URL, Base, engine

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# SQLite cannot ALTER a column: altering one means building a new table,
# copying the rows across and swapping it in. Batch mode makes Alembic write
# that sequence for us, and without it the first migration that changes a
# column type or a constraint fails outright on the catalog's own database.
RENDER_AS_BATCH = DATABASE_URL.startswith("sqlite")


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it -- `alembic upgrade --sql`."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=RENDER_AS_BATCH,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=RENDER_AS_BATCH,
        # Off by default, so a column that changed type would otherwise be
        # detected as no change at all.
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run the migrations, on the caller's connection where there is one.

    app/migrate.py passes the connection it has already opened, so the startup
    upgrade runs through a single connection rather than asking SQLite to write
    through two at once. From the alembic command line there is no such
    connection and the app's engine supplies one.
    """
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    with engine.connect() as connection:
        _run(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
