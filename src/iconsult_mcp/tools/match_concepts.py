"""Deterministic concept matching via embedding similarity."""

import hashlib
import re
from datetime import datetime, timezone

from iconsult_mcp.db import (
    create_consultation,
    get_project,
    search_canonical_concepts_by_embedding,
    search_concepts_by_embedding,
)
from iconsult_mcp.embed import embed_query


def _normalize_text(text: str) -> str:
    """Normalize text for fingerprinting: lowercase, collapse whitespace, strip."""
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _project_fingerprint(text: str) -> str:
    """SHA-256 of normalized project description."""
    return hashlib.sha256(_normalize_text(text).encode("utf-8")).hexdigest()


async def match_concepts(
    project_description: str,
    max_results: int = 15,
    similarity_threshold: float = 0.3,
    project_id: str | None = None,
) -> dict:
    """Match a project description to knowledge graph concepts via embedding similarity.

    Args:
        project_description: Free-text description of the user's project.
        max_results: Maximum concepts to return (default 15).
        similarity_threshold: Minimum cosine similarity (default 0.3).
        project_id: Optional. When provided AND the project's unified KG has
            been built (`build_project_kg`), search the per-project canonical
            concept layer (deduplicated across triaged books) instead of the
            global concept space. Returned concepts carry `member_concept_ids`,
            `role`, and `rubric_pattern_id`. When omitted, behaviour is
            identical to the legacy single-book path.
    """
    if not project_description or not project_description.strip():
        return {"error": "project_description must be a non-empty string"}

    max_results = max(1, min(50, max_results))

    project_scoped = project_id is not None and project_id != ""
    if project_scoped:
        project = get_project(project_id)
        if project is None:
            return {"error": f"Project '{project_id}' not found"}
        if project.get("unified_kg_built_at") is None:
            return {
                "error": (
                    f"Project '{project_id}' has not built its unified knowledge "
                    f"graph yet. Call build_project_kg(project_id='{project_id}') first."
                )
            }

    query_embedding = await embed_query(project_description)

    if project_scoped:
        results = search_canonical_concepts_by_embedding(
            query_embedding,
            project_id=project_id,
            max_results=max_results,
        )
    else:
        results = search_concepts_by_embedding(query_embedding, max_results=max_results)

    matched = [r for r in results if r["score"] >= similarity_threshold]

    fingerprint = _project_fingerprint(project_description)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    consultation_id = f"{fingerprint[:12]}_{timestamp}"

    concept_ids = [m["id"] for m in matched]
    scores = [m["score"] for m in matched]

    create_consultation(
        consultation_id=consultation_id,
        fingerprint=fingerprint,
        description=project_description,
        concept_ids=concept_ids,
        scores=scores,
        project_id=project_id if project_scoped else None,
    )

    if project_scoped:
        matched_payload = [
            {
                "id": m["id"],
                "name": m["name"],
                "role": m["role"],
                "rubric_pattern_id": m["rubric_pattern_id"],
                "member_concept_ids": m["member_concept_ids"],
                "score": m["score"],
            }
            for m in matched
        ]
    else:
        matched_payload = [
            {"id": m["id"], "name": m["name"], "category": m["category"], "score": m["score"]}
            for m in matched
        ]

    response = {
        "consultation_id": consultation_id,
        "project_fingerprint": fingerprint,
        "matched_concepts": matched_payload,
    }
    if project_scoped:
        response["project_id"] = project_id
        response["scope"] = "project_canonical"
    return response
