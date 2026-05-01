"""Phase 4c — project-scoped ask_book tests.

Covers:
- Backwards compatibility: project_id omitted → legacy response (no
  scope/project_id keys).
- Error paths: unknown project_id, project KG not built.
- Canonical concept_ids expand to source-book member IDs before section
  search; expanded members surface in the response.
- Passages scope to project's triaged_book_ids — passage book_id is always
  in the triaged set.
- Auto-pickup of project_id from the consultation row (matches 4b pattern).
- Suggested questions are derived from expanded members.

Tests seed canonical_concepts directly and rely on real arsanjani
sections / relationships for the section-search and edge-derivation
paths.
"""

from __future__ import annotations

import pytest

from iconsult_mcp.db import (
    create_consultation,
    create_project,
    mark_project_kg_built,
    upsert_canonical_concept,
)
from iconsult_mcp.tools.ask_book import ask_book


_AGENTIC_DESCRIPTION = (
    "Multi-agent system with supervisor patterns, fault tolerance, and "
    "task delegation."
)

_SUPERVISOR_MEMBER = "arsanjani_2026__supervisor_architecture"
_DELEGATION_MEMBER = "arsanjani_2026__task_delegation_frameworks"
_SWARM_MEMBER = "arsanjani_2026__swarm_architecture"


def _seed_supervisor_project(pid: str, register_project) -> str:
    """Single-book project with one canonical cluster covering supervisor +
    task_delegation_frameworks (both arsanjani). Returns the canonical_id.
    """
    register_project(pid)
    create_project(
        project_id=pid,
        name="phase4c-test",
        description=_AGENTIC_DESCRIPTION,
        triaged_book_ids=["arsanjani_2026"],
    )
    canonical_id = f"{pid}__multi_agent_topology"
    upsert_canonical_concept(
        canonical_id=canonical_id,
        project_id=pid,
        name="Multi-Agent Topology",
        member_concept_ids=[_SUPERVISOR_MEMBER, _DELEGATION_MEMBER],
        role="supporting_evidence",
        rubric_pattern_id="supervisor_architecture",
        canonical_embedding=None,
    )
    mark_project_kg_built(pid)
    return canonical_id


# --- backwards compatibility -----------------------------------------------


@pytest.mark.asyncio
async def test_ask_book_no_project_id_legacy_shape():
    """Without project_id, response has no scope / project_id keys."""
    result = await ask_book(
        question="What is supervisor architecture?",
        max_passages=2,
    )
    assert "error" not in result, result.get("error")
    assert "scope" not in result
    assert "project_id" not in result
    assert "expanded_member_concept_ids" not in result
    assert result["passage_count"] >= 1


# --- error paths -----------------------------------------------------------


@pytest.mark.asyncio
async def test_ask_book_unknown_project_id_returns_error():
    result = await ask_book(
        question="anything",
        project_id="proj_does_not_exist_xyz",
    )
    assert "error" in result
    assert "not found" in result["error"]


@pytest.mark.asyncio
async def test_ask_book_project_kg_not_built_returns_error(project_cleanup):
    register_project, _ = project_cleanup
    pid = register_project("test_ask_book_kg_not_built")
    create_project(
        project_id=pid,
        name="kg-not-built",
        description="placeholder",
        triaged_book_ids=["arsanjani_2026"],
    )

    result = await ask_book(question="anything", project_id=pid)
    assert "error" in result
    assert "build_project_kg" in result["error"]


# --- project-scoped happy path ---------------------------------------------


@pytest.mark.asyncio
async def test_ask_book_canonical_concept_ids_expand_to_members(project_cleanup):
    """Canonical concept_ids get expanded to source-book member IDs,
    surfaced in the response."""
    register_project, _ = project_cleanup
    canonical_id = _seed_supervisor_project(
        "test_ask_book_expand", register_project
    )

    result = await ask_book(
        question="How does the supervisor delegate tasks?",
        concept_ids=[canonical_id],
        project_id="test_ask_book_expand",
        max_passages=3,
    )

    assert "error" not in result, result.get("error")
    assert result["scope"] == "project_canonical"
    assert result["project_id"] == "test_ask_book_expand"
    expanded = result["expanded_member_concept_ids"]
    assert set(expanded) == {_SUPERVISOR_MEMBER, _DELEGATION_MEMBER}


@pytest.mark.asyncio
async def test_ask_book_passages_scoped_to_triaged_books(project_cleanup):
    """Passages all carry a book_id that's in the project's triaged set."""
    register_project, _ = project_cleanup
    _seed_supervisor_project("test_ask_book_book_scope", register_project)

    result = await ask_book(
        question="How does the supervisor delegate tasks?",
        project_id="test_ask_book_book_scope",
        max_passages=5,
    )
    assert "error" not in result, result.get("error")
    assert result["passages"], "expected at least one passage"
    for p in result["passages"]:
        assert p.get("book_id") == "arsanjani_2026", (
            f"passage book_id should be in triaged set: {p}"
        )


@pytest.mark.asyncio
async def test_ask_book_unknown_canonical_id_silently_dropped(project_cleanup):
    """Canonical IDs not in this project are dropped during expansion;
    if all are dropped, expanded_member_concept_ids is empty (no concept-level
    filter applied beyond the book_ids scope)."""
    register_project, _ = project_cleanup
    _seed_supervisor_project("test_ask_book_unknown_id", register_project)

    result = await ask_book(
        question="anything",
        concept_ids=["test_ask_book_unknown_id__not_a_real_canonical"],
        project_id="test_ask_book_unknown_id",
        max_passages=2,
    )
    assert "error" not in result
    assert result["expanded_member_concept_ids"] == []


@pytest.mark.asyncio
async def test_ask_book_suggested_questions_from_expanded_members(project_cleanup):
    """Suggested questions are derived from the expanded members' edges."""
    register_project, _ = project_cleanup
    canonical_id = _seed_supervisor_project(
        "test_ask_book_suggested_q", register_project
    )

    result = await ask_book(
        question="How do supervisor patterns delegate tasks?",
        concept_ids=[canonical_id],
        project_id="test_ask_book_suggested_q",
        max_passages=2,
    )
    assert "error" not in result
    # Both members have a deep edge graph in arsanjani; expect non-empty
    # suggested questions sourced from those edges.
    assert result.get("suggested_questions"), (
        f"expected suggested_questions from expanded members, got: {result}"
    )


# --- auto-pickup from consultation row -------------------------------------


@pytest.mark.asyncio
async def test_ask_book_auto_pickup_from_consultation(
    project_cleanup, consultation_cleanup
):
    """consultation_id with project_id on the row → ask_book routes through
    the canonical layer without an explicit project_id arg."""
    register_project, _ = project_cleanup
    canonical_id = _seed_supervisor_project(
        "test_ask_book_autopickup", register_project
    )

    cid = consultation_cleanup("ask_book_autopickup_001")
    create_consultation(
        consultation_id=cid,
        fingerprint="ask_book_autopickup_fp",
        description=_AGENTIC_DESCRIPTION,
        concept_ids=[canonical_id],
        scores=[1.0],
        project_id="test_ask_book_autopickup",
    )

    result = await ask_book(
        question="anything about supervisors",
        concept_ids=[canonical_id],
        consultation_id=cid,
        max_passages=2,
    )
    assert "error" not in result, result.get("error")
    assert result["scope"] == "project_canonical"
    assert result["project_id"] == "test_ask_book_autopickup"
    assert set(result["expanded_member_concept_ids"]) == {
        _SUPERVISOR_MEMBER, _DELEGATION_MEMBER,
    }


@pytest.mark.asyncio
async def test_ask_book_consultation_without_project_id_stays_legacy(
    consultation_cleanup,
):
    """A legacy (project_id=NULL) consultation does NOT trigger canonical routing."""
    cid = consultation_cleanup("ask_book_legacy_001")
    create_consultation(
        consultation_id=cid,
        fingerprint="ask_book_legacy_fp",
        description=_AGENTIC_DESCRIPTION,
        concept_ids=[_SUPERVISOR_MEMBER],
        scores=[1.0],
        project_id=None,
    )
    result = await ask_book(
        question="anything",
        concept_ids=[_SUPERVISOR_MEMBER],
        consultation_id=cid,
        max_passages=2,
    )
    assert "error" not in result, result.get("error")
    assert "scope" not in result
    assert "project_id" not in result
    assert "expanded_member_concept_ids" not in result
