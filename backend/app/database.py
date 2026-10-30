import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./specvault.db")
IS_SQLITE = DATABASE_URL.startswith("sqlite")

# check_same_thread=False is needed for SQLite specifically —
# it allows the connection to be used across the threads FastAPI spawns per request.
# This flag doesn't exist for Postgres and would error there, so it's SQLite-only.
connect_args = {"check_same_thread": False} if IS_SQLITE else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)


if IS_SQLITE:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):
        """SQLite's defaults suit one person on one machine, not a catalog a
        lab reads at once. Set per connection, because that is the only scope
        two of these have.

        * journal_mode=WAL is the file's own setting and persists, but is set
          here so a database restored from a copy gets it too. Readers no
          longer block on the one person saving a library.
        * foreign_keys is OFF by default, per connection, every time. Without
          it a library's paths outlive the library they belong to.
        * busy_timeout waits for a writer instead of failing at once, which is
          the difference between a save that takes a moment and one that
          reports "database is locked".
        """
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()