"""Bounded graph traversal from seed concepts."""

from iconsult_mcp.db import (
    get_canonical_subgraph,
    get_consultation,
    get_project,
    get_subgraph as db_get_subgraph,
    log_consultation_step,
)


async def get_subgraph(
    concept_ids: list[str],
    max_hops: int = 2,
    confidence_threshold: float = 0.5,
    max_edges: int = 50,
    include_descriptions: bool = False,
    consultation_id: str | None = None,
    project_id: str | None = None,
) -> dict:
    """Priority-queue traversal from seed concepts, returning compact nodes and edges.

    Args:
        concept_ids: List of concept IDs to start from. When project-scoped,
            these should be canonical concept IDs (`{project_id}__{slug}`)
            rather than book-scoped IDs.
        max_hops: Maximum traversal depth (1-3, default 2).
        confidence_threshold: Minimum edge confidence (0.0-1.0, default 0.5).
        max_edges: Maximum edges to return (1-200, default 50).
        include_descriptions: Include edge description text (default False).
        consultation_id: Optional consultation ID to log this step. If the
            consultation row carries a project_id (set by `match_concepts`)
            and the explicit `project_id` arg is omitted, the project_id is
            auto-picked up from the row so callers don't have to re-pass it.
        project_id: Optional. When provided AND the project's unified KG has
            been built (`build_project_kg`), traversal runs over the canonical
            edge view: each canonical seed expands to its source-book members,
            BFS runs across `relationships`, and results collapse back to
            canonical clusters with max-confidence edge collapse (option 1 —
            one edge per `(from_canonical, to_canonical)` pair, keeping the
            highest-confidence source edge's relationship_type). When
            omitted, behaviour is identical to the legacy single-book path.
    """
    if not concept_ids:
        return {"error": "concept_ids must be a non-empty list"}

    max_hops = max(1, min(3, max_hops))
    max_edges = max(1, min(200, max_edges))

    effective_project_id = project_id
    if effective_project_id is None and consultation_id:
        consult = get_consultation(consultation_id)
        if consult and consult.get("project_id"):
            effective_project_id = consult["project_id"]

    if effective_project_id:
        project = get_project(effective_project_id)
        if project is None:
            return {"error": f"Project '{effective_project_id}' not found"}
        if project.get("unified_kg_built_at") is None:
            return {
                "error": (
                    f"Project '{effective_project_id}' has not built its unified "
                    f"knowledge graph yet. Call build_project_kg(project_id="
                    f"'{effective_project_id}') first."
                )
            }
        result = get_canonical_subgraph(
            seed_canonical_ids=concept_ids,
            project_id=effective_project_id,
            max_hops=max_hops,
            confidence_threshold=confidence_threshold,
            max_edges=max_edges,
            include_descriptions=include_descriptions,
        )
    else:
        result = db_get_subgraph(
            seed_concept_ids=concept_ids,
            max_hops=max_hops,
            confidence_threshold=confidence_threshold,
            max_edges=max_edges,
            include_descriptions=include_descriptions,
        )

    if consultation_id:
        discovered_ids = [n["id"] for n in result["nodes"] if not n.get("is_seed")]
        rel_types = list({e["type"] for e in result["edges"]})
        log_consultation_step(consultation_id, "get_subgraph", {
            "seed_concept_ids": concept_ids,
            "discovered_concept_ids": discovered_ids,
            "relationship_types_seen": rel_types,
            "node_count": len(result["nodes"]),
            "edge_count": len(result["edges"]),
            "project_id": effective_project_id,
            "scope": "project_canonical" if effective_project_id else "global",
        })

    response = {
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
    if effective_project_id:
        response["project_id"] = effective_project_id
        response["scope"] = "project_canonical"
    return response
