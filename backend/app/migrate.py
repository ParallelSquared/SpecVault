"""Bring the catalog's schema up to date, at startup.

The server runs its own migrations rather than leaving them to a step someone
has to remember on deployment day. A catalog whose schema is one release behind
does not fail at startup where it would be noticed -- it fails on whichever
request first touches the new column, in front of whoever happened to make it.

This replaces Base.metadata.create_all(). create_all() creates tables that are
missing and silently leaves alone every table that already exists, so it adds
no column to a database that already has the table -- which is every database
after the first run. Adding a field is a documented, routine change here, so
that difference is the whole point.
"""
import logging
import os

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect

from .database import engine

log = logging.getLogger(__name__)

# alembic.ini and migrations/ live in backend/, one level up from app/
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_PATH = os.path.join(_BACKEND_DIR, "alembic.ini")

# The migration that creates the schema as it stood when migrations were
# introduced. A database built by create_all() before that already matches it.
BASELINE = "722fc51941ab"


def _config() -> Config:
    config = Config(_CONFIG_PATH)
    # Config() resolves script_location against the working directory, which is
    # whatever the service was started in, so it is pinned here instead.
    config.set_main_option("script_location", os.path.join(_BACKEND_DIR, "migrations"))
    return config


def _needs_stamping(connection) -> bool:
    """True for a database built by create_all() before migrations existed:
    it has the catalog's table but no record of a migration ever running.

    Upgrading such a database without saying so would replay the baseline and
    fail on a table that is already there, which is the one way this transition
    can go wrong. Stamping it says "you are already at the baseline" -- true,
    because create_all() built it from the same models.
    """
    if MigrationContext.configure(connection).get_current_revision() is not None:
        return False
    return inspect(connection).has_table("libraries")


def run() -> None:
    """Upgrade the database to the newest migration, in place."""
    config = _config()
    with engine.begin() as connection:
        # Hand Alembic the open connection; env.py uses it rather than opening
        # a second one, so SQLite is not asked to write through two at once.
        config.attributes["connection"] = connection
        if _needs_stamping(connection):
            log.info("Existing pre-migration database found; stamping %s", BASELINE)
            command.stamp(config, BASELINE)
        command.upgrade(config, "head")
