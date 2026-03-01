"""Bounded graph traversal from seed concepts."""

from iconsult_mcp.db import get_subgraph as db_get_subgraph


async def get_subgraph(
    concept_ids: list[str],
    max_hops: int = 2,
    confidence_threshold: float = 0.0,
) -> dict:
    """BFS traversal from seed concepts, returning nodes and edges.

    Args:
        concept_ids: List of concept IDs to start from.
        max_hops: Maximum traversal depth (1-3, default 2).
        confidence_threshold: Minimum edge confidence to traverse.
    """
    if not concept_ids:
        return {"error": "concept_ids must be a non-empty list"}

    max_hops = max(1, min(3, max_hops))

    result = db_get_subgraph(
        seed_concept_ids=concept_ids,
        max_hops=max_hops,
        confidence_threshold=confidence_threshold,
    )

    return {
        "seed_concept_ids": concept_ids,
        "max_hops": max_hops,
        "confidence_threshold": confidence_threshold,
        "node_count": len(result["nodes"]),
        "edge_count": len(result["edges"]),
        "nodes": result["nodes"],
        "edges": result["edges"],
    }
