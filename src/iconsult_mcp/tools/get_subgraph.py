"""Bounded graph traversal from seed concepts."""

from iconsult_mcp.db import get_subgraph as db_get_subgraph


async def get_subgraph(
    concept_ids: list[str],
    max_hops: int = 2,
    confidence_threshold: float = 0.5,
    max_edges: int = 50,
    include_descriptions: bool = False,
) -> dict:
    """Priority-queue traversal from seed concepts, returning compact nodes and edges.

    Args:
        concept_ids: List of concept IDs to start from.
        max_hops: Maximum traversal depth (1-3, default 2).
        confidence_threshold: Minimum edge confidence (0.0-1.0, default 0.5).
        max_edges: Maximum edges to return (1-200, default 50).
        include_descriptions: Include edge description text (default False).
    """
    if not concept_ids:
        return {"error": "concept_ids must be a non-empty list"}

    max_hops = max(1, min(3, max_hops))
    max_edges = max(1, min(200, max_edges))

    result = db_get_subgraph(
        seed_concept_ids=concept_ids,
        max_hops=max_hops,
        confidence_threshold=confidence_threshold,
        max_edges=max_edges,
        include_descriptions=include_descriptions,
    )

    return {
        "seed_concept_ids": concept_ids,
        "max_hops": max_hops,
        "confidence_threshold": confidence_threshold,
        "max_edges": max_edges,
        "node_count": len(result["nodes"]),
        "edge_count": len(result["edges"]),
        "truncated": result["truncated"],
        "total_edges_found": result["total_edges_found"],
        "nodes": result["nodes"],
        "edges": result["edges"],
    }
