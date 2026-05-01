"""Phase 4a — project-scoped match_concepts tests.

Covers:
- Backwards compatibility: project_id omitted → legacy shape, NULL project_id
  on consultations row.
- Error paths: unknown project_id, project KG not built.
- Happy path: seeded project + canonical_concepts → returns canonical IDs
  with member_concept_ids, role, rubric_pattern_id; persists project_id on
  the consultations row; threshold filtering works.

Tests seed canonical_concepts directly (cheap) rather than running the full
build_project_kg pipeline; build_project_kg integration is covered in
test_build_project_kg.py.
"""

from __future__ import annotations

import pytest

from iconsult_mcp.db import (
    create_project,
    get_consultation,
    mark_project_kg_built,
    upsert_canonical_concept,
)
from iconsult_mcp.embed import embed_query
from iconsult_mcp.tools.match_concepts import match_concepts


_AGENTIC_DESCRIPTION = (
    "We are building a multi-agent system where specialized AI agents "
    "coordinate to handle complex business workflows. The architecture "
    "needs supervisor patterns, fault tolerance, and reflection."
)


async def _seed_project_with_canonical(
    pid: str,
    register_project,
) -> tuple[str, list[str]]:
    """Create a project, seed one canonical_concepts row whose embedding
    matches `_AGENTIC_DESCRIPTION`, and mark the KG as built.

    Returns (canonical_id, member_ids) for assertions.
    """
    register_project(pid)
    create_project(
        project_id=pid,
        name="phase4a-test",
        description=_AGENTIC_DESCRIPTION,
        triaged_book_ids=["arsanjani_2026"],
    )
    seed_embedding = await embed_query(_AGENTIC_DESCRIPTION)
    canonical_id = f"{pid}__supervisor_architecture"
    member_ids = ["arsanjani_2026__supervisor_architecture"]
    upsert_canonical_concept(
        canonical_id=canonical_id,
        project_id=pid,
        name="Supervisor Architecture",
        member_concept_ids=member_ids,
        role="supporting_evidence",
        rubric_pattern_id="supervisor_architecture",
        canonical_embedding=seed_embedding,
    )
    mark_project_kg_built(pid)
    return canonical_id, member_ids


# --- backwards compatibility -----------------------------------------------


@pytest.mark.asyncio
async def test_match_concepts_no_project_id_legacy_shape(consultation_cleanup):
    """Without project_id, response shape and behaviour are unchanged."""
    result = await match_concepts(_AGENTIC_DESCRIPTION, max_results=10)
    consultation_cleanup(result["consultation_id"])

    assert "error" not in result, result.get("error")
    assert "scope" not in result, "scope key only set on project-scoped responses"
    assert "project_id" not in result
    assert result["matched_concepts"], "expected at least one match"

    first = result["matched_concepts"][0]
    assert set(first.keys()) == {"id", "name", "category", "score"}


@pytest.mark.asyncio
async def test_match_concepts_no_project_id_persists_null(consultation_cleanup):
    """Legacy call leaves consultations.project_id = NULL."""
    result = await match_concepts(_AGENTIC_DESCRIPTION, max_results=5)
    cid = consultation_cleanup(result["consultation_id"])
    row = get_consultation(cid)
    assert row is not None
    assert row["project_id"] is None


# --- error paths -----------------------------------------------------------


@pytest.mark.asyncio
async def test_match_concepts_unknown_project_id_returns_error():
    """Caller-supplied project_id that doesn't exist → error, no consultation."""
    result = await match_concepts(
        _AGENTIC_DESCRIPTION,
        project_id="proj_does_not_exist_xyz",
    )
    assert "error" in result
    assert "not found" in result["error"]
    assert "consultation_id" not in result


@pytest.mark.asyncio
async def test_match_concepts_project_kg_not_built_returns_error(project_cleanup):
    """Project exists but unified_kg_built_at is NULL → directs to build_project_kg."""
    register_project, _ = project_cleanup
    pid = register_project("test_match_kg_not_built")
    create_project(
        project_id=pid,
        name="kg-not-built",
        description="placeholder",
        triaged_book_ids=["arsanjani_2026"],
    )
    # NOT calling mark_project_kg_built — this is the error path

    result = await match_concepts(_AGENTIC_DESCRIPTION, project_id=pid)
    assert "error" in result
    assert "build_project_kg" in result["error"]
    assert "consultation_id" not in result


# --- project-scoped happy path ---------------------------------------------


@pytest.mark.asyncio
async def test_match_concepts_project_scoped_returns_canonical_shape(
    project_cleanup, consultation_cleanup
):
    """Project-scoped match returns canonical IDs + member_concept_ids + role."""
    register_project, _ = project_cleanup
    canonical_id, member_ids = await _seed_project_with_canonical(
        "test_match_proj_scoped", register_project
    )

    result = await match_concepts(
        _AGENTIC_DESCRIPTION,
        project_id="test_match_proj_scoped",
        max_results=10,
    )
    consultation_cleanup(result["consultation_id"])

    assert "error" not in result, result.get("error")
    assert result["scope"] == "project_canonical"
    assert result["project_id"] == "test_match_proj_scoped"
    assert result["matched_concepts"], "expected the seeded cluster"

    seeded = next(
        (m for m in result["matched_concepts"] if m["id"] == canonical_id),
        None,
    )
    assert seeded is not None, (
        f"seeded canonical {canonical_id} not in matches: "
        f"{[m['id'] for m in result['matched_concepts']]}"
    )
    assert seeded["role"] == "supporting_evidence"
    assert seeded["rubric_pattern_id"] == "supervisor_architecture"
    assert seeded["member_concept_ids"] == member_ids
    # canonical shape uses role/rubric_pattern_id, NOT the legacy `category` field
    assert "category" not in seeded


@pytest.mark.asyncio
async def test_match_concepts_project_scoped_persists_project_id(
    project_cleanup, consultation_cleanup
):
    """Successful project-scoped call writes project_id onto consultations row."""
    register_project, _ = project_cleanup
    await _seed_project_with_canonical("test_match_proj_persist", register_project)

    result = await match_concepts(
        _AGENTIC_DESCRIPTION,
        project_id="test_match_proj_persist",
    )
    cid = consultation_cleanup(result["consultation_id"])
    row = get_consultation(cid)
    assert row is not None
    assert row["project_id"] == "test_match_proj_persist"


@pytest.mark.asyncio
async def test_match_concepts_project_scoped_threshold_filters(
    project_cleanup, consultation_cleanup
):
    """High similarity_threshold filters out low-relevance canonical concepts."""
    register_project, _ = project_cleanup
    await _seed_project_with_canonical("test_match_proj_threshold", register_project)

    # Far-from-seeded description; cosine similarity to the agentic seed
    # embedding should fall well below 0.95.
    unrelated = "A simple recipe management web app for home cooks."
    result = await match_concepts(
        unrelated,
        project_id="test_match_proj_threshold",
        similarity_threshold=0.95,
    )
    consultation_cleanup(result["consultation_id"])

    assert "error" not in result, result.get("error")
    assert result["matched_concepts"] == []
