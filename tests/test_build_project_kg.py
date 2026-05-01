"""Phase 3c — build_project_kg tests.

Covers the in-process clustering + role-classification helpers (pure
Python, no DB / LLM) and one integration test that exercises the full
build against the live `concept_alignment_cache` populated for the
arsanjani_2026 / gulli_2025 pair (skipped if either book is absent or
the cache is empty).
"""

from __future__ import annotations

import pytest

from iconsult_mcp.db import get_connection, list_canonical_concepts
from iconsult_mcp.tools.projects import (
    _UnionFind,
    _classify_cluster_role,
    _mean_embedding,
    _pick_canonical_name,
    _slugify,
    build_project_kg,
    start_project,
)


# --- pure-python helpers ---------------------------------------------------


def test_unionfind_basic_clustering():
    uf = _UnionFind(["a", "b", "c", "d", "e"])
    uf.union("a", "b")
    uf.union("b", "c")
    uf.union("d", "e")
    clusters = sorted(sorted(c) for c in uf.clusters().values())
    assert clusters == [["a", "b", "c"], ["d", "e"]]


def test_unionfind_singleton_preserved():
    """Items never unioned remain singleton clusters."""
    uf = _UnionFind(["a", "b", "c"])
    uf.union("a", "b")
    clusters = sorted(sorted(c) for c in uf.clusters().values())
    assert clusters == [["a", "b"], ["c"]]


def test_unionfind_idempotent_unions():
    uf = _UnionFind(["a", "b", "c"])
    uf.union("a", "b")
    uf.union("a", "b")  # no-op
    uf.union("b", "a")  # no-op (other direction)
    assert len(uf.clusters()) == 2  # {a,b} and {c}


def test_classify_cluster_role_supporting_evidence_via_rubric():
    """Any member that resolves to a rubric pattern anchors the cluster."""
    role, rubric_pid = _classify_cluster_role([
        "arsanjani_2026__supervisor_architecture",
        "gulli_2025__some_unrelated_thing",
    ])
    assert role == "supporting_evidence"
    assert rubric_pid == "supervisor_architecture"


def test_classify_cluster_role_informational_only():
    """Cluster with no rubric-anchored member → informational_only."""
    role, rubric_pid = _classify_cluster_role([
        "gulli_2025__langgraph",
        "gulli_2025__crewai",
    ])
    assert role == "informational_only"
    assert rubric_pid is None


def test_classify_cluster_role_resolves_alias():
    """Old MATURITY_MODEL-style IDs are resolved through aliases."""
    role, rubric_pid = _classify_cluster_role([
        "arsanjani_2026__function_calling_pattern",  # alias → single_agent_baseline
    ])
    assert role == "supporting_evidence"
    assert rubric_pid == "single_agent_baseline"


def test_pick_canonical_name_prefers_oracle_book():
    concepts = {
        "arsanjani_2026__a": {
            "id": "arsanjani_2026__a", "name": "MCP", "book_id": "arsanjani_2026",
        },
        "gulli_2025__a": {
            "id": "gulli_2025__a", "name": "Model Context Protocol (MCP) extended description",
            "book_id": "gulli_2025",
        },
    }
    name = _pick_canonical_name(
        ["arsanjani_2026__a", "gulli_2025__a"],
        concepts,
        oracle_book_id="arsanjani_2026",
    )
    assert name == "MCP"


def test_pick_canonical_name_no_oracle_uses_shortest():
    """Without an oracle present, picks the shortest member name."""
    concepts = {
        "b1__x": {"id": "b1__x", "name": "Tool Use Pattern with Function Calling Extension", "book_id": "b1"},
        "b2__x": {"id": "b2__x", "name": "Tool Use", "book_id": "b2"},
    }
    name = _pick_canonical_name(
        ["b1__x", "b2__x"], concepts, oracle_book_id=None,
    )
    assert name == "Tool Use"


def test_mean_embedding_arithmetic():
    result = _mean_embedding([[1.0, 2.0, 3.0], [3.0, 4.0, 5.0]])
    assert result == [2.0, 3.0, 4.0]


def test_mean_embedding_handles_empty():
    """Empty input returns a zero-vector (defensive default)."""
    from iconsult_mcp.config import EMBEDDING_DIMENSIONS
    out = _mean_embedding([])
    assert len(out) == EMBEDDING_DIMENSIONS
    assert all(x == 0.0 for x in out)


def test_slugify_basic():
    assert _slugify("Model Context Protocol (MCP)") == "model_context_protocol_mcp"


def test_slugify_truncates():
    long = "A " * 100
    assert len(_slugify(long, limit=60)) <= 60


# --- input validation -----------------------------------------------------


@pytest.mark.asyncio
async def test_build_project_kg_unknown_project():
    r = await build_project_kg(project_id="proj_does_not_exist_xyz")
    assert "error" in r
    assert "not found" in r["error"]


@pytest.mark.asyncio
async def test_build_project_kg_zero_book_project(project_cleanup):
    """Briefing: 3c refuses to run on a project with zero triaged books."""
    register_project, _ = project_cleanup
    pid = register_project("test_build_zero_books")

    from iconsult_mcp.db import create_project
    create_project(
        project_id=pid,
        name="empty",
        description="empty",
        triaged_book_ids=[],
    )

    r = await build_project_kg(project_id=pid)
    assert "error" in r
    assert "no triaged_book_ids" in r["error"]


# --- integration ----------------------------------------------------------


@pytest.mark.asyncio
async def test_build_project_kg_against_live_corpus(project_cleanup):
    """Full integration: start a project on (arsanjani_2026, gulli_2025),
    build the KG, verify canonical_concepts rows + at least one
    cross-book cluster + role classification.

    Skipped when either book or the alignment cache is missing.
    """
    register_project, _ = project_cleanup
    conn = get_connection()
    book_ids = {
        r[0] for r in conn.execute("SELECT DISTINCT book_id FROM concepts").fetchall()
    }
    if "arsanjani_2026" not in book_ids or "gulli_2025" not in book_ids:
        pytest.skip("requires both arsanjani_2026 and gulli_2025 ingested")

    cached = conn.execute(
        "SELECT COUNT(*) FROM concept_alignment_cache WHERE same_concept = TRUE"
    ).fetchone()[0]
    if cached == 0:
        pytest.skip("requires concept_alignment_cache to be populated")

    started = await start_project(
        name="test_build_kg_live",
        project_description="multi-agent system with reflection, tool use, MCP, supervisor patterns, fault tolerance",
        triaged_book_ids=["arsanjani_2026", "gulli_2025"],
    )
    pid = started["project_id"]
    register_project(pid)

    # auto_align disabled — we trust the existing cache (the live
    # `align_book_pair` run that populated it during this session).
    result = await build_project_kg(project_id=pid, auto_align=False)
    assert "error" not in result, result.get("error")
    assert result["skipped"] is False
    assert result["concepts_total"] > 0
    assert result["clusters_total"] >= 1
    assert result["by_role"]["supporting_evidence"] >= 1, (
        "expected at least one supporting_evidence cluster (rubric-anchored "
        "concepts in arsanjani_2026 should anchor at least one)"
    )

    # Canonical_concepts rows actually exist in the DB
    canonicals = list_canonical_concepts(pid)
    assert len(canonicals) == result["clusters_total"]

    # At least one multi-book cluster (e.g. MCP, ADK, HITL — these were
    # high-confidence alignments in the run).
    multi_member = [c for c in result["preview_clusters"] if c["member_count"] >= 2]
    assert multi_member, "expected at least one multi-member cluster"
    cross_book = [
        c for c in multi_member if len(c["member_books"]) >= 2
    ]
    assert cross_book, "expected at least one cross-book canonical cluster"

    # Role assignment is sane: every supporting_evidence cluster has a
    # non-null rubric_pattern_id; every informational_only has None.
    for c in canonicals:
        if c["role"] == "supporting_evidence":
            assert c["rubric_pattern_id"] is not None
        else:
            assert c["rubric_pattern_id"] is None


@pytest.mark.asyncio
async def test_build_project_kg_idempotent_skip(project_cleanup):
    """A second build call on a built project is skipped unless force=True."""
    register_project, _ = project_cleanup
    conn = get_connection()
    book_ids = {
        r[0] for r in conn.execute("SELECT DISTINCT book_id FROM concepts").fetchall()
    }
    if "arsanjani_2026" not in book_ids:
        pytest.skip("requires arsanjani_2026 ingested")

    started = await start_project(
        name="test_build_kg_idempotent",
        project_description="single-book test for idempotent build behavior",
        triaged_book_ids=["arsanjani_2026"],
    )
    pid = started["project_id"]
    register_project(pid)

    r1 = await build_project_kg(project_id=pid, auto_align=False)
    assert r1["skipped"] is False

    r2 = await build_project_kg(project_id=pid, auto_align=False)
    assert r2["skipped"] is True
    assert "already built" in r2["reason"]

    r3 = await build_project_kg(project_id=pid, auto_align=False, force=True)
    assert r3["skipped"] is False
