"""Shared fixtures for iconsult integration tests.

These tests require:
  - MOTHERDUCK_TOKEN env var (database access)
  - OPENAI_API_KEY env var (embeddings)

Run with: py -m pytest tests/ -v
"""

import os

import pytest

# Skip entire test suite if credentials are missing
pytestmark = pytest.mark.skipif(
    not os.environ.get("MOTHERDUCK_TOKEN") or not os.environ.get("OPENAI_API_KEY"),
    reason="MOTHERDUCK_TOKEN and OPENAI_API_KEY required for integration tests",
)


@pytest.fixture(scope="session", autouse=True)
def ensure_db_connection():
    """Ensure DB connection is established once for the session."""
    from iconsult_mcp.db import get_connection, close_connection

    get_connection()
    yield
    close_connection()


@pytest.fixture()
def consultation_cleanup():
    """Track consultation IDs created during a test and clean them up after."""
    created_ids: list[str] = []

    def register(consultation_id: str):
        created_ids.append(consultation_id)
        return consultation_id

    yield register

    # Cleanup: remove test consultations
    from iconsult_mcp.db import get_connection

    conn = get_connection()
    for cid in created_ids:
        try:
            conn.execute("DELETE FROM consultations WHERE id = ?", [cid])
        except Exception:
            pass
