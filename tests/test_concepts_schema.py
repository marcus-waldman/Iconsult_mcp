"""Multi-book concepts table schema tests.

Phase 3 regression: verifies the composite UNIQUE(name, book_id) constraint
on `concepts` so the same concept name can coexist across books — the
single-book era enforced UNIQUE(name) and silently dropped the highest-
confidence cross-book alignment candidates. The migration helper
`_migrate_concepts_name_unique` runs from `_init_schema` on every
connection open and is idempotent; these tests pin the desired end-state
constraint shape and behaviour.
"""

from __future__ import annotations

import pytest

from iconsult_mcp.db import get_connection


_TEST_NAME_PREFIX = "__test_concepts_schema__"


@pytest.fixture()
def concept_cleanup():
    """Track concept rows inserted during a test by name prefix."""
    yield
    conn = get_connection()
    conn.execute(
        "DELETE FROM concepts WHERE name LIKE ?",
        [f"{_TEST_NAME_PREFIX}%"],
    )


def test_concepts_unique_constraint_is_composite():
    """Constraint shape: UNIQUE(name, book_id), no UNIQUE(name) alone."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT constraint_type, constraint_column_names
        FROM duckdb_constraints()
        WHERE table_name = 'concepts'
        """
    ).fetchall()

    unique_constraints = [
        sorted(cols) for ctype, cols in rows if ctype == "UNIQUE"
    ]
    assert ["book_id", "name"] in unique_constraints, (
        f"missing composite UNIQUE(name, book_id); got: {unique_constraints}"
    )
    assert ["name"] not in unique_constraints, (
        "legacy UNIQUE(name) should have been dropped by migration; "
        f"got: {unique_constraints}"
    )


def test_same_name_different_books_coexist(concept_cleanup):
    """The same concept name can live in two books simultaneously."""
    conn = get_connection()
    name = f"{_TEST_NAME_PREFIX}shared_concept"

    conn.execute(
        "INSERT INTO concepts (id, name, book_id) VALUES (?, ?, ?)",
        [f"book_a__{name}", name, "book_a"],
    )
    conn.execute(
        "INSERT INTO concepts (id, name, book_id) VALUES (?, ?, ?)",
        [f"book_b__{name}", name, "book_b"],
    )

    count = conn.execute(
        "SELECT COUNT(*) FROM concepts WHERE name = ?", [name]
    ).fetchone()[0]
    assert count == 2


def test_same_name_same_book_rejected(concept_cleanup):
    """Within one book, name still has to be unique."""
    conn = get_connection()
    name = f"{_TEST_NAME_PREFIX}duplicate_in_one_book"

    conn.execute(
        "INSERT INTO concepts (id, name, book_id) VALUES (?, ?, ?)",
        [f"book_a__{name}_first", name, "book_a"],
    )
    with pytest.raises(Exception):
        conn.execute(
            "INSERT INTO concepts (id, name, book_id) VALUES (?, ?, ?)",
            [f"book_a__{name}_second", name, "book_a"],
        )


def test_arsanjani_and_gulli_share_concept_names_post_migration():
    """Live data check: the 5 documented shared concepts each have rows in
    both books after the migration. Skips if either book is absent."""
    conn = get_connection()
    book_ids = {
        r[0]
        for r in conn.execute("SELECT DISTINCT book_id FROM concepts").fetchall()
    }
    if "arsanjani_2026" not in book_ids or "gulli_2025" not in book_ids:
        pytest.skip("requires both arsanjani_2026 and gulli_2025 ingested")

    shared = conn.execute(
        """
        SELECT name
        FROM concepts
        WHERE book_id IN ('arsanjani_2026', 'gulli_2025')
        GROUP BY name
        HAVING COUNT(DISTINCT book_id) = 2
        """
    ).fetchall()
    shared_names = {r[0] for r in shared}

    expected_subset = {
        "Agent Development Kit (ADK)",
        "CrewAI",
        "Human-in-the-Loop (HITL)",
        "LangGraph",
        "Model Context Protocol (MCP)",
    }
    missing = expected_subset - shared_names
    assert not missing, (
        f"these concepts should appear in both books post-migration but only "
        f"in one: {missing}"
    )
