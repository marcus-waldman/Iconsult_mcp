"""Deterministic concept matching via embedding similarity."""

import hashlib
import re
from datetime import datetime, timezone

from iconsult_mcp.db import create_consultation, search_concepts_by_embedding
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
) -> dict:
    """Match a project description to knowledge graph concepts via embedding similarity.

    Args:
        project_description: Free-text description of the user's project.
        max_results: Maximum concepts to return (default 15).
        similarity_threshold: Minimum cosine similarity (default 0.3).
    """
    if not project_description or not project_description.strip():
        return {"error": "project_description must be a non-empty string"}

    max_results = max(1, min(50, max_results))

    # Embed and search
    query_embedding = await embed_query(project_description)
    results = search_concepts_by_embedding(query_embedding, max_results=max_results)

    # Filter by threshold
    matched = [r for r in results if r["score"] >= similarity_threshold]

    # Generate IDs
    fingerprint = _project_fingerprint(project_description)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    consultation_id = f"{fingerprint[:12]}_{timestamp}"

    concept_ids = [m["id"] for m in matched]
    scores = [m["score"] for m in matched]

    # Persist
    create_consultation(
        consultation_id=consultation_id,
        fingerprint=fingerprint,
        description=project_description,
        concept_ids=concept_ids,
        scores=scores,
    )

    return {
        "consultation_id": consultation_id,
        "project_fingerprint": fingerprint,
        "matched_concepts": [
            {"id": m["id"], "name": m["name"], "category": m["category"], "score": m["score"]}
            for m in matched
        ],
    }
