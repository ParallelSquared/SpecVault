"""The migrations and the models must describe the same schema.

Everything else in this suite builds its tables straight from the models, so a
field added to models.py and not to a migration would pass every other test
here and then be missing from the catalog's own database -- which is the exact
failure migrations were introduced to prevent. These tests are what makes the
migrations trustworthy rather than decorative.
"""
import sqlite3

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app import migrate, models  # noqa: F401  -- registers the tables
from app.database import Base


@pytest.fixture
def migrated(tmp_path):
    """An engine over a database built by running every migration."""
    engine = create_engine(f"sqlite:///{(tmp_path / 'migrated.db').as_posix()}")
    config = migrate._config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    yield engine
    engine.dispose()


def test_migrations_match_the_models(migrated):
    """Running the migrations produces the schema the models describe."""
    with migrated.connect() as connection:
        context = MigrationContext.configure(
            connection, opts={"compare_type": True, "target_metadata": Base.metadata}
        )
        differences = compare_metadata(context, Base.metadata)

    assert differences == [], (
        "The migrations and the models disagree. Add a migration for the "
        "change: `alembic revision --autogenerate -m \"...\"`. Differences:\n"
        + "\n".join(str(d) for d in differences)
    )


def test_migrations_are_a_single_chain():
    """One head, so `upgrade head` is never ambiguous."""
    from alembic.script import ScriptDirectory

    heads = ScriptDirectory.from_config(migrate._config()).get_heads()
    assert len(heads) == 1, f"expected one migration head, found {heads}"


def test_baseline_is_the_first_migration():
    """app/migrate.py stamps BASELINE onto pre-migration databases, so it has
    to be the revision whose schema create_all() used to build."""
    from alembic.script import ScriptDirectory

    scripts = ScriptDirectory.from_config(migrate._config())
    assert scripts.get_revision(migrate.BASELINE).down_revision is None


def test_upgrade_leaves_a_pre_migration_database_alone(tmp_path):
    """A database built by create_all() before migrations existed is stamped,
    not rebuilt -- and the rows in it survive."""
    path = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(bind=engine)  # how such a database was built
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO libraries (path, creator) VALUES ('L:/old.tsv', 'someone')"
        )
    engine.dispose()

    engine = create_engine(f"sqlite:///{path.as_posix()}")
    config = migrate._config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        assert migrate._needs_stamping(connection)
        command.stamp(config, migrate.BASELINE)
        command.upgrade(config, "head")
    engine.dispose()

    rows = sqlite3.connect(path).execute("SELECT path, creator FROM libraries").fetchall()
    assert rows == [("L:/old.tsv", "someone")]


def test_fresh_database_is_marked_as_migrated(tmp_path):
    """A database the migrations built records that they ran, so the next
    upgrade continues from there rather than replaying the baseline."""
    engine = create_engine(f"sqlite:///{(tmp_path / 'fresh.db').as_posix()}")
    config = migrate._config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    with engine.connect() as connection:
        assert MigrationContext.configure(connection).get_current_revision() is not None
        assert inspect(connection).has_table("libraries")
    engine.dispose()
