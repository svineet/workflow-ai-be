import os
import pathlib
import sys
import time
from typing import Generator

import pytest
from fastapi.testclient import TestClient

# Ensure project root is on sys.path so `import app...` works
PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Use a file-based SQLite DB for stability across connections
TEST_DB_PATH = pathlib.Path(__file__).parent / "test.db"


@pytest.fixture(scope="session", autouse=True)
def _set_test_env() -> None:
    # Ensure a clean DB file for the test session
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB_PATH.absolute()}"
    # Optional envs used by the app; keep empty for offline tests
    os.environ.setdefault("GCS_BUCKET", "")
    os.environ.setdefault("OPENAI_API_KEY", "")


@pytest.fixture(scope="session")
def client() -> Generator[TestClient, None, None]:
    # Import app after env is set so the engine binds to SQLite
    from app.server.main import app

    with TestClient(app) as c:
        # Give startup hooks a moment if needed (table creation)
        time.sleep(0.05)
        yield c 