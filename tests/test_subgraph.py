"""Test graph traversal returns meaningful neighborhoods for matched concepts."""

import pytest

from tests.cases import CASES

from iconsult_mcp.tools.match_concepts import match_concepts
from iconsult_mcp.db import get_subgraph


# Use a subset of cases to limit API calls during graph tests
GRAPH_CASES = [c for c in CASES if c["id"] in (
    "financial_research", "customer_service", "human_in_the_loop", "agents_as_tools",
)]


@pytest.fixture(params=GRAPH_CASES, ids=[c["id"] for c in GRAPH_CASES])
def matched_case(request, consultation_cleanup):
    """Pre-match concepts for a case, return (case, matched_concept_ids)."""
    return request.param


@pytest.mark.asyncio
async def test_subgraph_returns_nodes_and_edges(matched_case, consultation_cleanup):
    """Subgraph from matched concepts has nodes and edges."""
    result = await match_concepts(matched_case["description"], max_results=5)
    consultation_cleanup(result["consultation_id"])

    concept_ids = [m["id"] for m in result["matched_concepts"][:3]]
    subgraph = get_subgraph(concept_ids, max_hops=1, confidence_threshold=0.3)

    assert len(subgraph["nodes"]) >= len(concept_ids), (
        f"Should have at least the seed nodes. Got {len(subgraph['nodes'])} nodes."
    )
    assert len(subgraph["edges"]) > 0, "Subgraph should have at least one edge"


@pytest.mark.asyncio
async def test_subgraph_seeds_are_marked(matched_case, consultation_cleanup):
    """Seed nodes are marked with is_seed=True."""
    result = await match_concepts(matched_case["description"], max_results=3)
    consultation_cleanup(result["consultation_id"])

    concept_ids = [m["id"] for m in result["matched_concepts"][:3]]
    subgraph = get_subgraph(concept_ids, max_hops=1)

    seed_nodes = [n for n in subgraph["nodes"] if n.get("is_seed")]
    seed_ids = {n["id"] for n in seed_nodes}

    for cid in concept_ids:
        assert cid in seed_ids, f"Seed concept '{cid}' not marked as seed in subgraph"


@pytest.mark.asyncio
async def test_subgraph_relationship_types(matched_case, consultation_cleanup):
    """Edges have valid relationship types."""
    result = await match_concepts(matched_case["description"], max_results=5)
    consultation_cleanup(result["consultation_id"])

    concept_ids = [m["id"] for m in result["matched_concepts"][:3]]
    subgraph = get_subgraph(concept_ids, max_hops=1, confidence_threshold=0.3)

    valid_types = {
        "uses", "component_of", "extends", "specializes",
        "alternative_to", "requires", "precedes", "enables",
        "conflicts_with", "complements", "related_to",
        "semantic_similarity",
    }

    for edge in subgraph["edges"]:
        assert "type" in edge, "Edge must have a type"
        assert edge["type"] in valid_types, (
            f"Unknown edge type '{edge['type']}'. Valid: {valid_types}"
        )


@pytest.mark.asyncio
async def test_subgraph_max_edges_respected():
    """max_edges parameter limits output."""
    # Use a broad concept that will have many edges
    subgraph = get_subgraph(
        ["supervisor_architecture"], max_hops=2, max_edges=5, confidence_threshold=0.3,
    )
    assert len(subgraph["edges"]) <= 5
