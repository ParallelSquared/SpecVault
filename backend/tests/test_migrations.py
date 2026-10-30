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
def lab(monkeypatch):
    """A configured lab share, as a deployment would have."""
    from app import share

    monkeypatch.setattr(share, "CONFIG", share.ShareConfig(
        server_root=r"\\PTI\Lab",
        mounts=[
            share.Mount(share.WINDOWS, r"\\PTI\Lab"),
            share.Mount(share.WINDOWS, "L:"),
            share.Mount(share.MAC, "/Volumes/Lab"),
        ],
    ))


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


def test_upgrade_leaves_a_pre_migration_database_alone(tmp_path, lab):
    """A database built by create_all() before migrations existed is stamped,
    not rebuilt -- and the rows in it survive every migration that then runs.

    Built by replaying the baseline and then forgetting that it ran, because
    that is the schema create_all() produced back then. Calling create_all()
    here would build today's schema instead and test nothing.
    """
    path = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    config = migrate._config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, migrate.BASELINE)
        connection.exec_driver_sql(
            "INSERT INTO libraries (path, creator) VALUES ('L:/old.tsv', 'someone')"
        )
        connection.exec_driver_sql("DROP TABLE alembic_version")
    engine.dispose()

    engine = create_engine(f"sqlite:///{path.as_posix()}")
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        assert migrate._needs_stamping(connection)
        command.stamp(config, migrate.BASELINE)
        command.upgrade(config, "head")
    engine.dispose()

    rows = sqlite3.connect(path).execute(
        "SELECT library_paths.path, libraries.creator FROM libraries"
        " JOIN library_paths ON library_paths.library_id = libraries.id"
    ).fetchall()
    # kept, made share-relative, and moved into the paths table
    assert rows == [("old.tsv", "someone")]


class TestPathsBecomeShareRelative:
    """The data migration that rewrites the paths already in the catalog.

    These rows were written before the share existed, each in whatever
    spelling the machine that added it used. Until they are converted the
    catalog holds two kinds of path, and the old ones cannot be recognised as
    duplicates of anything.
    """

    BEFORE_PATHS = "722fc51941ab"
    # This migration, not head: later ones move path out of the libraries
    # table altogether, and these tests are about what this one does to it.
    AFTER_PATHS = "3b69dad453b9"

    @pytest.fixture
    def catalog(self, tmp_path, lab):
        """A catalog as it was before: absolute paths, in several spellings."""
        engine = create_engine(f"sqlite:///{(tmp_path / 'old.db').as_posix()}")
        config = migrate._config()
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, self.BEFORE_PATHS)
            connection.exec_driver_sql(
                "INSERT INTO libraries (path, creator, creation_log_path, fasta_path)"
                " VALUES (?, ?, ?, ?)",
                (r"L:\Libraries\one.tsv", "z", r"L:\Libraries\report.log.txt",
                 r"L:\Fasta\human.fasta; L:\Fasta\mouse.fasta"),
            )
            connection.exec_driver_sql(
                "INSERT INTO libraries (path, creator) VALUES (?, ?)",
                ("/Volumes/Lab/Libraries/two.tsv", "z"),
            )
            connection.exec_driver_sql(
                "INSERT INTO libraries (path, creator) VALUES (?, ?)",
                (r"C:\off-share\three.tsv", "z"),
            )
        yield engine
        engine.dispose()

    def paths(self, engine):
        with engine.connect() as connection:
            return connection.exec_driver_sql(
                "SELECT path, creation_log_path, fasta_path FROM libraries ORDER BY id"
            ).fetchall()

    def move(self, engine, target, up=True):
        config = migrate._config()
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            (command.upgrade if up else command.downgrade)(config, target)

    def test_every_spelling_becomes_the_same_relative_form(self, catalog):
        self.move(catalog, self.AFTER_PATHS)
        rows = self.paths(catalog)
        assert rows[0][0] == "Libraries/one.tsv"
        assert rows[1][0] == "Libraries/two.tsv"

    def test_log_and_fasta_paths_are_rewritten_too(self, catalog):
        self.move(catalog, self.AFTER_PATHS)
        row = self.paths(catalog)[0]
        assert row[1] == "Libraries/report.log.txt"
        # several FASTAs are one field, each converted on its own
        assert row[2] == "Fasta/human.fasta; Fasta/mouse.fasta"

    def test_a_path_off_the_share_is_left_alone(self, catalog):
        """resolve() still opens it; inventing a translation would be worse."""
        self.move(catalog, self.AFTER_PATHS)
        assert self.paths(catalog)[2][0] == r"C:\off-share\three.tsv"

    def test_the_rows_survive(self, catalog):
        self.move(catalog, self.AFTER_PATHS)
        assert len(self.paths(catalog)) == 3

    def test_downgrade_restores_absolute_paths(self, catalog):
        self.move(catalog, self.AFTER_PATHS)
        self.move(catalog, self.BEFORE_PATHS, up=False)
        rows = self.paths(catalog)
        assert rows[0][0] == r"\\PTI\Lab\Libraries\one.tsv"
        assert rows[1][0] == r"\\PTI\Lab\Libraries\two.tsv"
        assert rows[2][0] == r"C:\off-share\three.tsv"

    def test_upgrading_twice_changes_nothing_more(self, catalog):
        """Already-canonical paths are not canonicalised again."""
        self.move(catalog, self.AFTER_PATHS)
        once = self.paths(catalog)
        self.move(catalog, self.BEFORE_PATHS, up=False)
        self.move(catalog, self.AFTER_PATHS)
        assert self.paths(catalog) == once

    def test_a_folder_named_like_a_mount_survives_a_second_upgrade(self, tmp_path, lab):
        """A library really stored under a folder called mnt/lab canonicalises
        to "mnt/lab/foo.tsv" -- which matches the Linux mount. Converting an
        already-relative path would quietly eat its first two folders."""
        engine = create_engine(f"sqlite:///{(tmp_path / 'tricky.db').as_posix()}")
        config = migrate._config()
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, self.BEFORE_PATHS)
            connection.exec_driver_sql(
                "INSERT INTO libraries (path, creator) VALUES (?, ?)",
                (r"L:\mnt\lab\foo.tsv", "z"),
            )

        self.move(engine, self.AFTER_PATHS)
        assert self.paths(engine)[0][0] == "mnt/lab/foo.tsv"
        # and again, as a downgrade-then-upgrade would
        self.move(engine, self.AFTER_PATHS)
        assert self.paths(engine)[0][0] == "mnt/lab/foo.tsv"
        engine.dispose()

    def test_a_catalog_with_paths_refuses_to_migrate_without_a_share(
        self, tmp_path, monkeypatch
    ):
        """It can only run once. Stamped as done against a server whose
        share.json had not been put in place yet, it would convert nothing and
        never be tried again -- so it stops instead."""
        from app import share

        engine = create_engine(f"sqlite:///{(tmp_path / 'noshare.db').as_posix()}")
        config = migrate._config()
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, self.BEFORE_PATHS)
            connection.exec_driver_sql(
                "INSERT INTO libraries (path, creator) VALUES (?, ?)",
                (r"L:\Libraries\one.tsv", "z"),
            )
        monkeypatch.setattr(share, "CONFIG", share.ShareConfig("", [], require_on_share=False))

        with pytest.raises(Exception, match="no lab share is configured"):
            self.move(engine, self.AFTER_PATHS)

        # and the row is untouched, so it can be migrated once the share is set up
        assert self.paths(engine)[0][0] == r"L:\Libraries\one.tsv"
        engine.dispose()

    def test_an_empty_catalog_migrates_without_a_share(self, tmp_path, monkeypatch):
        """A fresh install has nothing to lose, and should not be blocked."""
        from app import share

        engine = create_engine(f"sqlite:///{(tmp_path / 'empty.db').as_posix()}")
        monkeypatch.setattr(share, "CONFIG", share.ShareConfig("", [], require_on_share=False))
        self.move(engine, self.AFTER_PATHS)
        with engine.connect() as connection:
            assert MigrationContext.configure(connection).get_current_revision() == "3b69dad453b9"
        engine.dispose()


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


class TestForeignKeysEnforced:
    """The path migrations, run the way a server with foreign keys on runs them.

    SQLite cannot drop a column: alembic's batch mode builds a new table,
    copies the rows, DROPs the old one and renames. With PRAGMA foreign_keys
    ON that DROP cascades into every table referencing it -- so the order the
    tables are built and dropped in decides whether the data survives.

    This suite's other tests run with enforcement off, which is SQLite's
    default and hid the bug completely: the migration moved every path into
    library_paths and the drop of the old libraries table then deleted them
    all, leaving libraries with no paths at all.
    """

    FIRST = "722fc51941ab"
    LAST = "d9e5a3fd6e68"

    @pytest.fixture
    def engine(self, tmp_path, lab):
        from sqlalchemy import event

        engine = create_engine(f"sqlite:///{(tmp_path / 'fk.db').as_posix()}")

        @event.listens_for(engine, "connect")
        def enforce(dbapi_connection, _record):
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

        yield engine
        engine.dispose()

    def move(self, engine, target, up=True):
        config = migrate._config()
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            (command.upgrade if up else command.downgrade)(config, target)

    def seed(self, engine):
        self.move(engine, self.FIRST)
        with engine.begin() as connection:
            for path in (r"L:\Libraries\one.tsv", r"L:\Libraries\two.tsv"):
                connection.exec_driver_sql(
                    "INSERT INTO libraries (path, creator) VALUES (?, ?)", (path, "z")
                )

    def paths(self, engine):
        with engine.connect() as connection:
            return sorted(
                row[0] for row in connection.exec_driver_sql(
                    "SELECT path FROM library_paths"
                ).fetchall()
            )

    def test_paths_survive_the_upgrade(self, engine):
        self.seed(engine)
        self.move(engine, "head")
        assert self.paths(engine) == ["Libraries/one.tsv", "Libraries/two.tsv"]

    def test_every_library_still_has_a_path(self, engine):
        """The failure this guards against left the libraries behind with no
        paths at all, which the API cannot even serialise."""
        self.seed(engine)
        self.move(engine, "head")
        with engine.connect() as connection:
            orphans = connection.exec_driver_sql(
                "SELECT COUNT(*) FROM libraries WHERE id NOT IN"
                " (SELECT library_id FROM library_paths)"
            ).scalar()
        assert orphans == 0

    def test_paths_survive_the_downgrade(self, engine):
        self.seed(engine)
        self.move(engine, "head")
        self.move(engine, self.FIRST, up=False)
        with engine.connect() as connection:
            rows = sorted(
                row[0] for row in connection.exec_driver_sql(
                    "SELECT path FROM libraries"
                ).fetchall()
            )
        assert rows == [r"\\PTI\Lab\Libraries\one.tsv", r"\\PTI\Lab\Libraries\two.tsv"]

    def test_extra_paths_survive_a_round_trip_to_head(self, engine):
        """A second copy is kept across upgrade, and the first survives the
        downgrade that has nowhere to put the second."""
        self.seed(engine)
        self.move(engine, "head")
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO library_paths (library_id, path) VALUES (1, 'Archive/one.tsv')"
            )
        assert len(self.paths(engine)) == 3

        self.move(engine, self.FIRST, up=False)
        self.move(engine, "head")
        # the extra copy is gone -- the old shape had nowhere for it -- but
        # every library still has the path it was catalogued at
        assert self.paths(engine) == ["Libraries/one.tsv", "Libraries/two.tsv"]
