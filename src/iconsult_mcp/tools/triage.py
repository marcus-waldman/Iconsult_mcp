"""Phase 2b — `triage_books` tool.

Deterministic triage layer: embed a project description, cosine-match it
against `books.summary_embedding`, return a ranked book list. With one
book registered the ranking is degenerate; the value emerges as the
corpus grows (Phase 6 onboards mid-level pattern books).

Pure read tool. Books whose `summary_embedding` is NULL are excluded.
"""

from __future__ import annotations

from iconsult_mcp.db import search_books_by_embedding
from iconsult_mcp.embed import embed_query


async def triage_books(
    project_description: str,
    top_k: int = 5,
    threshold: float = 0.4,
) -> dict:
    """Rank registered books by cosine similarity to a project description.

    Args:
        project_description: Free-text project description.
        top_k: Maximum books to return (1-50, default 5).
        threshold: Minimum cosine score to include (0.0-1.0, default 0.4).
    """
    if not project_description or not project_description.strip():
        return {"error": "project_description must be a non-empty string"}

    top_k = max(1, min(50, int(top_k)))
    threshold = max(0.0, min(1.0, float(threshold)))

    query_embedding = await embed_query(project_description)
    ranked = search_books_by_embedding(
        query_embedding=query_embedding,
        max_results=top_k,
        threshold=threshold,
    )

    return {
        "ranked_books": [
            {
                "id": b["id"],
                "title": b["title"],
                "altitude": b["altitude"],
                "is_oracle": b["is_oracle"],
                "score": b["score"],
            }
            for b in ranked
        ],
        "total_above_threshold": len(ranked),
        "threshold": threshold,
    }
