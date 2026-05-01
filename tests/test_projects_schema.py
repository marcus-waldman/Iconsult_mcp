"""Phase 3a — projects + canonical_concepts + concept_alignment_cache tests.

Stage 3a only ships schema, helpers, and the `list_books` tool — no alignment
or KG-build logic yet. These tests verify the storage primitives round-trip
and that pair-order normalization is consistent. Real adjudication arrives
in stage 3c against a second book.
"""

from __future__ import annotations

import pytest

from iconsult_mcp.config import EMBEDDING_DIMENSIONS
from iconsult_mcp.db import (
    create_project,
    get_alignment_decision,
    get_canonical_concept,
    get_connection,
    get_project,
    list_canonical_concepts,
    list_projects,
    mark_project_kg_built,
    record_alignment_decision,
    upsert_canonical_concept,
)
from iconsult_mcp.tools.projects import list_books


# --- schema -----------------------------------------------------------------


def test_phase3a_tables_exist():
    """All three Phase 3a tables exist with expected columns."""
    conn = get_connection()
    expected = {
        "projects": {
            "id", "name", "description", "triaged_book_ids",
            "unified_kg_built_at", "created_at",
        },
        "canonical_concepts": {
            "id", "project_id", "name", "member_concept_ids", "role",
            "rubric_pattern_id", "canonical_embedding",
        },
        "concept_alignment_cache": {
            "concept_a_id", "concept_b_id", "same_concept", "confidence",
            "rationale", "created_at",
        },
    }
    for table, cols in expected.items():
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
            [table],
        ).fetchall()
        actual = {r[0] for r in rows}
        missing = cols - actual
        assert not missing, f"{table} missing columns: {missing}"


# --- projects ---------------------------------------------------------------


def test_create_and_get_project(project_cleanup):
    register_project, _ = project_cleanup
    pid = register_project("test_proj_create_get")
    create_project(
        pid,
        name="Phase 3a Test Project",
        description="A test project for schema round-trip",
        triaged_book_ids=["arsanjani_2026"],
    )
    record = get_project(pid)
    assert record is not None
    assert record["id"] == pid
    assert record["name"] == "Phase 3a Test Project"
    assert record["description"] == "A test project for schema round-trip"
    assert record["triaged_book_ids"] == ["arsanjani_2026"]
    assert record["unified_kg_built_at"] is None
    assert record["created_at"] is not None


def test_get_project_returns_none_for_unknown_id():
    assert get_project("test_proj_does_not_exist_xyz") is None


def test_create_project_is_upsert(project_cleanup):
    """Re-inserting with the same id replaces the row."""
    register_project, _ = project_cleanup
    pid = register_project("test_proj_upsert")
    create_project(pid, name="v1", description="first", triaged_book_ids=["a"])
    create_project(pid, name="v2", description="second", triaged_book_ids=["b", "c"])
    record = get_project(pid)
    assert record is not None
    assert record["name"] == "v2"
    assert record["description"] == "second"
    assert record["triaged_book_ids"] == ["b", "c"]


def test_list_projects_includes_created(project_cleanup):
    register_project, _ = project_cleanup
    pid = register_project("test_proj_list")
    create_project(pid, name="Listing Test", description="x", triaged_book_ids=[])
    ids = [p["id"] for p in list_projects()]
    assert pid in ids


def test_mark_project_kg_built(project_cleanup):
    register_project, _ = project_cleanup
    pid = register_project("test_proj_built_marker")
    create_project(pid, name="Built Marker", description="x", triaged_book_ids=[])
    assert get_project(pid)["unified_kg_built_at"] is None
    mark_project_kg_built(pid)
    assert get_project(pid)["unified_kg_built_at"] is not None


def test_create_project_with_empty_triaged_books(project_cleanup):
    register_project, _ = project_cleanup
    pid = register_project("test_proj_empty_triage")
    create_project(pid, name="No Triage Yet", description="x", triaged_book_ids=None)
    record = get_project(pid)
    assert record["triaged_book_ids"] == []


# --- canonical_concepts -----------------------------------------------------


def test_upsert_and_get_canonical_concept(project_cleanup):
    register_project, _ = project_cleanup
    pid = register_project("test_proj_canon")
    create_project(pid, name="Canon Test", description="x", triaged_book_ids=[])

    canonical_id = f"{pid}__supervisor"
    upsert_canonical_concept(
        canonical_id=canonical_id,
        project_id=pid,
        name="Supervisor",
        member_concept_ids=["arsanjani_2026__supervisor"],
        role="supporting_evidence",
        rubric_pattern_id="supervisor",
        canonical_embedding=[0.0] * EMBEDDING_DIMENSIONS,
    )

    record = get_canonical_concept(canonical_id)
    assert record is not None
    assert record["id"] == canonical_id
    assert record["project_id"] == pid
    assert record["name"] == "Supervisor"
    assert record["member_concept_ids"] == ["arsanjani_2026__supervisor"]
    assert record["role"] == "supporting_evidence"
    assert record["rubric_pattern_id"] == "supervisor"
    assert record["has_embedding"] is True


def test_upsert_canonical_concept_informational_only(project_cleanup):
    register_project, _ = project_cleanup
    pid = register_project("test_proj_canon_info")
    create_project(pid, name="Info Test", description="x", triaged_book_ids=[])

    canonical_id = f"{pid}__background_concept"
    upsert_canonical_concept(
        canonical_id=canonical_id,
        project_id=pid,
        name="Background Concept",
        member_concept_ids=["other_book__bg"],
        role="informational_only",
        rubric_pattern_id=None,
        canonical_embedding=None,
    )
    record = get_canonical_concept(canonical_id)
    assert record["role"] == "informational_only"
    assert record["rubric_pattern_id"] is None
    assert record["has_embedding"] is False


def test_upsert_canonical_concept_invalid_role_raises(project_cleanup):
    register_project, _ = project_cleanup
    pid = register_project("test_proj_canon_bad_role")
    create_project(pid, name="Bad Role Test", description="x", triaged_book_ids=[])
    with pytest.raises(ValueError, match="role must be"):
        upsert_canonical_concept(
            canonical_id=f"{pid}__x",
            project_id=pid,
            name="X",
            member_concept_ids=["a"],
            role="totally_invalid",
        )


def test_upsert_canonical_concept_empty_members_raises(project_cleanup):
    register_project, _ = project_cleanup
    pid = register_project("test_proj_canon_empty_members")
    create_project(pid, name="Empty Members", description="x", triaged_book_ids=[])
    with pytest.raises(ValueError, match="member_concept_ids"):
        upsert_canonical_concept(
            canonical_id=f"{pid}__x",
            project_id=pid,
            name="X",
            member_concept_ids=[],
            role="informational_only",
        )


def test_list_canonical_concepts_scopes_to_project(project_cleanup):
    register_project, _ = project_cleanup
    pid_a = register_project("test_proj_scope_a")
    pid_b = register_project("test_proj_scope_b")
    create_project(pid_a, name="A", description="a", triaged_book_ids=[])
    create_project(pid_b, name="B", description="b", triaged_book_ids=[])

    upsert_canonical_concept(
        canonical_id=f"{pid_a}__c1",
        project_id=pid_a,
        name="A-only concept",
        member_concept_ids=["x"],
        role="informational_only",
    )
    upsert_canonical_concept(
        canonical_id=f"{pid_b}__c1",
        project_id=pid_b,
        name="B-only concept",
        member_concept_ids=["y"],
        role="informational_only",
    )

    a_rows = list_canonical_concepts(pid_a)
    b_rows = list_canonical_concepts(pid_b)
    assert {r["id"] for r in a_rows} == {f"{pid_a}__c1"}
    assert {r["id"] for r in b_rows} == {f"{pid_b}__c1"}


def test_canonical_concept_role_check_constraint(project_cleanup):
    """The CHECK constraint on `role` blocks raw SQL bypass attempts too."""
    register_project, _ = project_cleanup
    pid = register_project("test_proj_canon_check")
    create_project(pid, name="Check Test", description="x", triaged_book_ids=[])

    conn = get_connection()
    with pytest.raises(Exception):
        conn.execute(
            """INSERT INTO canonical_concepts
               (id, project_id, name, member_concept_ids, role)
               VALUES (?, ?, ?, ?, ?)""",
            [f"{pid}__bad", pid, "Bad", ["x"], "garbage_role"],
        )


# --- concept_alignment_cache ------------------------------------------------


def test_record_and_get_alignment_decision(project_cleanup):
    _, register_alignment = project_cleanup
    a = "test_book_a__concept_one"
    b = "test_book_b__concept_one"
    register_alignment(a, b)

    record_alignment_decision(
        concept_a_id=a,
        concept_b_id=b,
        same_concept=True,
        confidence=0.91,
        rationale="Both describe a top-level coordinator over worker agents.",
    )
    decision = get_alignment_decision(a, b)
    assert decision is not None
    assert decision["same_concept"] is True
    assert decision["confidence"] == pytest.approx(0.91)
    assert "top-level" in decision["rationale"]


def test_alignment_decision_pair_order_normalized(project_cleanup):
    """Either argument order resolves to the same cache row."""
    _, register_alignment = project_cleanup
    a = "test_book_a__beta"
    b = "test_book_b__beta"  # lexicographically later than a
    register_alignment(a, b)

    record_alignment_decision(b, a, same_concept=False, confidence=0.2, rationale="diff")

    forward = get_alignment_decision(a, b)
    reverse = get_alignment_decision(b, a)
    assert forward is not None
    assert reverse is not None
    assert forward == reverse
    # Stored in canonical (lexicographic) order: a < b
    assert forward["concept_a_id"] == a
    assert forward["concept_b_id"] == b


def test_alignment_decision_is_idempotent(project_cleanup):
    """Re-recording the same pair overwrites — no PK violation."""
    _, register_alignment = project_cleanup
    a = "test_book_a__gamma"
    b = "test_book_b__gamma"
    register_alignment(a, b)

    record_alignment_decision(a, b, same_concept=False, confidence=0.3)
    record_alignment_decision(a, b, same_concept=True, confidence=0.95, rationale="updated")

    decision = get_alignment_decision(a, b)
    assert decision["same_concept"] is True
    assert decision["confidence"] == pytest.approx(0.95)
    assert decision["rationale"] == "updated"


def test_alignment_decision_distinct_pairs_dont_collide(project_cleanup):
    """Two unrelated pairs each get their own cache row."""
    _, register_alignment = project_cleanup
    a1 = "test_book_a__one"
    b1 = "test_book_b__one"
    a2 = "test_book_a__two"
    b2 = "test_book_b__two"
    register_alignment(a1, b1)
    register_alignment(a2, b2)

    record_alignment_decision(a1, b1, same_concept=True, confidence=0.9)
    record_alignment_decision(a2, b2, same_concept=False, confidence=0.1)

    d1 = get_alignment_decision(a1, b1)
    d2 = get_alignment_decision(a2, b2)
    assert d1["same_concept"] is True
    assert d2["same_concept"] is False


def test_get_alignment_decision_returns_none_when_uncached():
    assert get_alignment_decision(
        "test_book_x__never_recorded_a",
        "test_book_y__never_recorded_b",
    ) is None


def test_record_alignment_decision_rejects_self_pair():
    with pytest.raises(ValueError, match="itself"):
        record_alignment_decision("same__concept", "same__concept", same_concept=True)


# --- list_books MCP tool ----------------------------------------------------


@pytest.mark.asyncio
async def test_list_books_returns_arsanjani():
    """`list_books` returns the registered corpus; arsanjani_2026 must be present."""
    result = await list_books()
    assert "books" in result
    assert "total" in result
    assert result["altitude_filter"] is None
    ids = [b["id"] for b in result["books"]]
    assert "arsanjani_2026" in ids
    assert result["total"] == len(result["books"])


@pytest.mark.asyncio
async def test_list_books_response_shape():
    result = await list_books()
    assert result["books"], "expected at least one book in the corpus"
    book = result["books"][0]
    for key in ["id", "title", "authors", "year", "altitude", "is_oracle",
                "chapter_boundaries"]:
        assert key in book, f"missing key: {key}"


@pytest.mark.asyncio
async def test_list_books_altitude_filter_matches():
    """Filter by the altitude that arsanjani_2026 carries; expect at least one hit."""
    # arsanjani_2026 is registered with altitude='mid_level' (Phase 1b seed).
    result = await list_books(altitude="mid_level")
    assert result["altitude_filter"] == "mid_level"
    ids = [b["id"] for b in result["books"]]
    assert "arsanjani_2026" in ids


@pytest.mark.asyncio
async def test_list_books_altitude_filter_excludes():
    """An altitude value no book carries returns an empty list."""
    result = await list_books(altitude="this_altitude_does_not_exist")
    assert result["books"] == []
    assert result["total"] == 0
