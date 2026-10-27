import os
import sys
import tempfile
from pathlib import Path

# Point the app at a throwaway database BEFORE importing any app module.
# database.py reads DATABASE_URL at import time, and load_dotenv() does not
# override a variable that is already set, so this wins over backend/.env.
# Without it the tests would open the real specvault.db.
_TMP_DB = Path(tempfile.mkdtemp(prefix="specvault-tests-")) / "test.db"
os.environ["DATABASE_URL"] = "sqlite:///" + _TMP_DB.as_posix()

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


def pytest_sessionstart(session):
    """Fail loudly rather than quietly writing to the developer's real catalog."""
    from app.database import DATABASE_URL

    assert "specvault-tests-" in DATABASE_URL, (
        f"tests are pointed at {DATABASE_URL!r}, not a temporary database"
    )


@pytest.fixture
def client():
    """A client over an empty database; tables are rebuilt for each test."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def make_library(client):
    """Insert a library and return its response body."""
    def _make(path, creator="tester", **fields):
        response = client.post("/libraries/", json={"path": path, "creator": creator, **fields})
        assert response.status_code == 201, response.text
        return response.json()

    return _make
