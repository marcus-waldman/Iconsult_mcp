"""Shared fixtures for iconsult integration tests.

These tests require:
  - OPENAI_API_KEY env var (embeddings)
  - ANTHROPIC_API_KEY env var (extraction tools that call Claude)

Database is local DuckDB at `data/iconsult.duckdb` (override with ICONSULT_DB).
The MotherDuck dependency was removed in the multi-book refactor (Phase 1a).

Run with: py -m pytest tests/ -v
"""

import os

import pytest

# Skip entire test suite if credentials are missing
pytestmark = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY") or not os.environ.get("ANTHROPIC_API_KEY"),
    reason="OPENAI_API_KEY and ANTHROPIC_API_KEY required for integration tests",
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

    # Cleanup: discard any buffered steps, then remove test data from DB
    from iconsult_mcp.db import get_connection, discard_pending_steps

    for cid in created_ids:
        discard_pending_steps(cid)

    conn = get_connection()
    for cid in created_ids:
        try:
            conn.execute("DELETE FROM implementation_plans WHERE consultation_id = ?", [cid])
        except Exception:
            pass
        try:
            conn.execute("DELETE FROM consultation_quality WHERE consultation_id = ?", [cid])
        except Exception:
            pass
        try:
            conn.execute("DELETE FROM blackboard_facts WHERE consultation_id = ?", [cid])
        except Exception:
            pass
        try:
            conn.execute("DELETE FROM consultation_state WHERE consultation_id = ?", [cid])
        except Exception:
            pass
        try:
            conn.execute("DELETE FROM consultation_events WHERE consultation_id = ?", [cid])
        except Exception:
            pass
        try:
            conn.execute("DELETE FROM consultations WHERE id = ?", [cid])
        except Exception:
            pass


@pytest.fixture()
def project_cleanup():
    """Track project IDs and concept_alignment_cache pairs created during a
    test and clean them up after.

    Phase 3a fixture. `register_project(pid)` removes the project row and any
    canonical_concepts that reference it. `register_alignment(a_id, b_id)`
    removes that single alignment-cache row (pair order doesn't matter).
    """
    project_ids: list[str] = []
    alignment_pairs: list[tuple[str, str]] = []

    def register_project(project_id: str) -> str:
        project_ids.append(project_id)
        return project_id

    def register_alignment(concept_a_id: str, concept_b_id: str) -> tuple[str, str]:
        alignment_pairs.append((concept_a_id, concept_b_id))
        return (concept_a_id, concept_b_id)

    yield register_project, register_alignment

    from iconsult_mcp.db import get_connection

    conn = get_connection()
    for pid in project_ids:
        try:
            conn.execute("DELETE FROM canonical_concepts WHERE project_id = ?", [pid])
        except Exception:
            pass
        try:
            conn.execute("DELETE FROM projects WHERE id = ?", [pid])
        except Exception:
            pass
    for a, b in alignment_pairs:
        # Delete both orderings to be safe — writer normalizes but tests may
        # register by either direction.
        for ordered_a, ordered_b in [(a, b), (b, a)]:
            try:
                conn.execute(
                    "DELETE FROM concept_alignment_cache "
                    "WHERE concept_a_id = ? AND concept_b_id = ?",
                    [ordered_a, ordered_b],
                )
            except Exception:
                pass
