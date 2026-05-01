"""Phase 4b — project-scoped get_subgraph tests.

Covers:
- Backwards compatibility: project_id omitted → legacy traversal, response shape
  unchanged.
- Error paths: unknown project_id, project KG not built.
- Canonical traversal: nodes returned as canonical IDs with member_concept_ids
  / role / rubric_pattern_id; intra-cluster source edges (where both endpoints
  live in the same canonical) are filtered; cross-cluster source edges
  collapse via option 1 (one canonical edge per (from_canonical, to_canonical)
  pair, highest-confidence source edge wins).
- Auto-pickup: when consultation_id is passed and the consultation row carries
  a project_id, get_subgraph routes through the canonical layer without an
  explicit project_id arg.

Tests seed canonical_concepts directly (cheap, no LLM) and rely on real
arsanjani relationships rows to exercise the traversal.
"""

from __future__ import annotations

import pytest

from iconsult_mcp.db import (
    create_consultation,
    create_project,
    get_consultation,
    get_canonical_subgraph,
    mark_project_kg_built,
    upsert_canonical_concept,
)
from iconsult_mcp.tools.get_subgraph import get_subgraph


_AGENTIC_DESCRIPTION = (
    "Multi-agent system with supervisor patterns, task delegation, "
    "and swarm coordination."
)

# Real arsanjani concept IDs with known relationships:
#   arsanjani_2026__supervisor_architecture --alternative_to-> arsanjani_2026__swarm_architecture (0.95)
#   arsanjani_2026__task_delegation_frameworks --component_of-> arsanjani_2026__swarm_architecture (0.9)
#   arsanjani_2026__task_delegation_frameworks --component_of-> arsanjani_2026__supervisor_architecture (0.9)  [intra-cluster]
_SUPERVISOR_MEMBER = "arsanjani_2026__supervisor_architecture"
_DELEGATION_MEMBER = "arsanjani_2026__task_delegation_frameworks"
_SWARM_MEMBER = "arsanjani_2026__swarm_architecture"


def _seed_two_cluster_project(pid: str, register_project) -> tuple[str, str]:
    """Cluster A = {supervisor, task_delegation_frameworks}, cluster B = {swarm}.

    Returns (cluster_a_id, cluster_b_id) for use in assertions.
    """
    register_project(pid)
    create_project(
        project_id=pid,
        name="phase4b-test",
        description=_AGENTIC_DESCRIPTION,
        triaged_book_ids=["arsanjani_2026"],
    )
    cluster_a_id = f"{pid}__multi_agent_topology"
    cluster_b_id = f"{pid}__swarm_architecture"
    upsert_canonical_concept(
        canonical_id=cluster_a_id,
        project_id=pid,
        name="Multi-Agent Topology",
        member_concept_ids=[_SUPERVISOR_MEMBER, _DELEGATION_MEMBER],
        role="supporting_evidence",
        rubric_pattern_id="supervisor_architecture",
        canonical_embedding=None,
    )
    upsert_canonical_concept(
        canonical_id=cluster_b_id,
        project_id=pid,
        name="Swarm Architecture",
        member_concept_ids=[_SWARM_MEMBER],
        role="informational_only",
        rubric_pattern_id=None,
        canonical_embedding=None,
    )
    mark_project_kg_built(pid)
    return cluster_a_id, cluster_b_id


# --- backwards compatibility -----------------------------------------------


@pytest.mark.asyncio
async def test_get_subgraph_no_project_id_legacy_shape():
    """Without project_id, response shape is unchanged (no scope/project_id keys)."""
    result = await get_subgraph(
        concept_ids=[_SUPERVISOR_MEMBER],
        max_hops=1,
        confidence_threshold=0.5,
    )
    assert "error" not in result, result.get("error")
    assert "scope" not in result
    assert "project_id" not in result
    # Legacy nodes don't carry member_concept_ids / role
    assert result["nodes"], "expected at least the seed node"
    seed_node = next(n for n in result["nodes"] if n.get("is_seed"))
    assert "member_concept_ids" not in seed_node
    assert "role" not in seed_node


# --- error paths -----------------------------------------------------------


@pytest.mark.asyncio
async def test_get_subgraph_unknown_project_id_returns_error():
    result = await get_subgraph(
        concept_ids=[_SUPERVISOR_MEMBER],
        project_id="proj_does_not_exist_xyz",
    )
    assert "error" in result
    assert "not found" in result["error"]


@pytest.mark.asyncio
async def test_get_subgraph_project_kg_not_built_returns_error(project_cleanup):
    register_project, _ = project_cleanup
    pid = register_project("test_subgraph_kg_not_built")
    create_project(
        project_id=pid,
        name="kg-not-built",
        description="placeholder",
        triaged_book_ids=["arsanjani_2026"],
    )
    # NOT calling mark_project_kg_built

    result = await get_subgraph(
        concept_ids=[f"{pid}__some_canonical"],
        project_id=pid,
    )
    assert "error" in result
    assert "build_project_kg" in result["error"]


# --- project-scoped happy path ---------------------------------------------


@pytest.mark.asyncio
async def test_get_subgraph_project_scoped_returns_canonical_nodes(project_cleanup):
    """Seeds are canonical; nodes carry member_concept_ids / role / rubric_pattern_id."""
    register_project, _ = project_cleanup
    cluster_a, cluster_b = _seed_two_cluster_project(
        "test_subgraph_canonical_nodes", register_project
    )

    result = await get_subgraph(
        concept_ids=[cluster_a],
        project_id="test_subgraph_canonical_nodes",
        max_hops=1,
        confidence_threshold=0.5,
    )

    assert "error" not in result, result.get("error")
    assert result["scope"] == "project_canonical"
    assert result["project_id"] == "test_subgraph_canonical_nodes"

    node_ids = {n["id"] for n in result["nodes"]}
    assert cluster_a in node_ids
    assert cluster_b in node_ids
    # No source-book concept IDs leak into nodes
    assert _SUPERVISOR_MEMBER not in node_ids
    assert _SWARM_MEMBER not in node_ids

    seed = next(n for n in result["nodes"] if n["id"] == cluster_a)
    assert seed["is_seed"] is True
    assert seed["role"] == "supporting_evidence"
    assert seed["rubric_pattern_id"] == "supervisor_architecture"
    assert set(seed["member_concept_ids"]) == {_SUPERVISOR_MEMBER, _DELEGATION_MEMBER}

    neighbour = next(n for n in result["nodes"] if n["id"] == cluster_b)
    assert neighbour["is_seed"] is False
    assert neighbour["role"] == "informational_only"
    assert neighbour["member_concept_ids"] == [_SWARM_MEMBER]


@pytest.mark.asyncio
async def test_get_subgraph_max_confidence_collapse(project_cleanup):
    """Two source edges A→B collapse to one canonical edge with max confidence."""
    register_project, _ = project_cleanup
    cluster_a, cluster_b = _seed_two_cluster_project(
        "test_subgraph_collapse", register_project
    )

    result = await get_subgraph(
        concept_ids=[cluster_a],
        project_id="test_subgraph_collapse",
        max_hops=1,
        confidence_threshold=0.5,
    )

    # Edges between cluster A and cluster B:
    #   supervisor → swarm (alternative_to, 0.95)  ← winner
    #   task_delegation_frameworks → swarm (component_of, 0.9)
    # → one canonical edge, type from the 0.95 winner.
    a_to_b = [e for e in result["edges"] if e["from"] == cluster_a and e["to"] == cluster_b]
    assert len(a_to_b) == 1, (
        f"expected exactly one canonical A→B edge, got {len(a_to_b)}: {a_to_b}"
    )
    edge = a_to_b[0]
    assert edge["type"] == "alternative_to"
    assert abs(edge["confidence"] - 0.95) < 0.01

    assert result["total_edges_found"] >= 1
    # The intra-cluster edge (task_delegation_frameworks → supervisor_architecture,
    # both in cluster A) must NOT appear as a canonical edge.
    intra = [e for e in result["edges"] if e["from"] == e["to"]]
    assert intra == [], f"intra-cluster edges should be filtered: {intra}"


@pytest.mark.asyncio
async def test_get_subgraph_canonical_helper_directly(project_cleanup):
    """Sanity check the DB helper in isolation (no tool layer)."""
    register_project, _ = project_cleanup
    cluster_a, cluster_b = _seed_two_cluster_project(
        "test_subgraph_helper_direct", register_project
    )

    result = get_canonical_subgraph(
        seed_canonical_ids=[cluster_a],
        project_id="test_subgraph_helper_direct",
        max_hops=1,
        confidence_threshold=0.5,
    )

    assert {n["id"] for n in result["nodes"]} == {cluster_a, cluster_b}
    a_to_b = [e for e in result["edges"] if e["from"] == cluster_a and e["to"] == cluster_b]
    assert len(a_to_b) == 1


@pytest.mark.asyncio
async def test_get_subgraph_unknown_canonical_seed_silently_dropped(project_cleanup):
    """Seed IDs not in the project's canonical layer are silently dropped
    (parallels legacy behaviour for unknown concept_ids)."""
    register_project, _ = project_cleanup
    cluster_a, _ = _seed_two_cluster_project(
        "test_subgraph_unknown_seed", register_project
    )

    result = await get_subgraph(
        concept_ids=[cluster_a, "test_subgraph_unknown_seed__does_not_exist"],
        project_id="test_subgraph_unknown_seed",
        max_hops=1,
        confidence_threshold=0.5,
    )
    assert "error" not in result
    node_ids = {n["id"] for n in result["nodes"]}
    assert cluster_a in node_ids
    assert "test_subgraph_unknown_seed__does_not_exist" not in node_ids


# --- auto-pickup of project_id from consultation row -----------------------


@pytest.mark.asyncio
async def test_get_subgraph_auto_pickup_from_consultation(
    project_cleanup, consultation_cleanup
):
    """Project_id on the consultations row routes get_subgraph through canonical
    even when the caller doesn't pass project_id explicitly."""
    register_project, _ = project_cleanup
    cluster_a, cluster_b = _seed_two_cluster_project(
        "test_subgraph_autopickup", register_project
    )

    cid = consultation_cleanup("autopickup_consult_001")
    create_consultation(
        consultation_id=cid,
        fingerprint="autopickup_test_fp",
        description=_AGENTIC_DESCRIPTION,
        concept_ids=[cluster_a, cluster_b],
        scores=[1.0, 0.9],
        project_id="test_subgraph_autopickup",
    )
    # Sanity: project_id landed on the row
    row = get_consultation(cid)
    assert row["project_id"] == "test_subgraph_autopickup"

    result = await get_subgraph(
        concept_ids=[cluster_a],
        consultation_id=cid,
        max_hops=1,
        confidence_threshold=0.5,
    )

    assert "error" not in result, result.get("error")
    assert result["scope"] == "project_canonical"
    assert result["project_id"] == "test_subgraph_autopickup"
    assert {n["id"] for n in result["nodes"]} == {cluster_a, cluster_b}


@pytest.mark.asyncio
async def test_get_subgraph_consultation_without_project_id_stays_legacy(
    consultation_cleanup
):
    """A legacy (project_id=NULL) consultation does NOT trigger canonical routing."""
    cid = consultation_cleanup("legacy_consult_001")
    create_consultation(
        consultation_id=cid,
        fingerprint="legacy_test_fp",
        description=_AGENTIC_DESCRIPTION,
        concept_ids=[_SUPERVISOR_MEMBER],
        scores=[1.0],
        project_id=None,
    )
    result = await get_subgraph(
        concept_ids=[_SUPERVISOR_MEMBER],
        consultation_id=cid,
        max_hops=1,
        confidence_threshold=0.5,
    )
    assert "error" not in result, result.get("error")
    assert "scope" not in result
    assert "project_id" not in result
