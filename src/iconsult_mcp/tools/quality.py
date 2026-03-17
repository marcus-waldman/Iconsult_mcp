"""Consultation quality tracking — user ratings and cross-consultation analytics.

Provides a feedback loop for improving consultation quality over time.
No LLM calls — stores ratings and computes trends from stored data.
"""

from iconsult_mcp.db import (
    get_consultation,
    insert_quality_rating,
    get_quality_ratings,
    log_consultation_step,
)


async def rate_consultation(
    consultation_id: str,
    rating: int | None = None,
    feedback: str | None = None,
) -> dict:
    """Rate a consultation's quality.

    Captures user satisfaction and optional free-text feedback. Automatically
    snapshots consultation metadata (coverage, pattern count, maturity level)
    for trend analysis.

    Args:
        consultation_id: The consultation session to rate.
        rating: Quality score 1-5 (optional).
        feedback: Free-text feedback (optional).
    """
    if not consultation_id or not consultation_id.strip():
        return {"error": "consultation_id is required"}

    if rating is None and feedback is None:
        return {"error": "At least one of rating or feedback is required"}

    if rating is not None:
        rating = max(1, min(5, rating))

    record = get_consultation(consultation_id)
    if not record:
        return {"error": f"Consultation '{consultation_id}' not found"}

    # Snapshot metadata from consultation steps
    steps = record.get("steps", [])
    pattern_count = sum(1 for s in steps if s.get("type") == "pattern_assessment")

    # Get coverage from consultation_report-type step or compute from steps
    matched_ids = set(record.get("matched_concept_ids", []))
    explored_ids = set()
    assessed_ids = set()
    for s in steps:
        if s.get("type") == "get_subgraph":
            explored_ids.update(s.get("seed_concept_ids", []))
        elif s.get("type") == "pattern_assessment":
            pid = s.get("pattern_id")
            if pid:
                assessed_ids.add(pid)

    engaged = explored_ids | assessed_ids
    concept_coverage = len(matched_ids & engaged) / len(matched_ids) if matched_ids else 0.0

    # Maturity level: check if score_architecture was run
    maturity_level = None
    for s in steps:
        if s.get("type") == "score_architecture":
            maturity_level = s.get("current_level")
            break

    record_id = insert_quality_rating(
        consultation_id=consultation_id,
        rating=rating,
        feedback=feedback,
        concept_coverage=round(concept_coverage, 3),
        pattern_count=pattern_count,
        maturity_level=maturity_level,
    )

    log_consultation_step(consultation_id, "quality_rated", {
        "rating": rating,
        "has_feedback": bool(feedback),
    })

    return {
        "consultation_id": consultation_id,
        "record_id": record_id,
        "rating": rating,
        "metadata_snapshot": {
            "concept_coverage": round(concept_coverage, 3),
            "pattern_count": pattern_count,
            "maturity_level": maturity_level,
        },
    }


async def consultation_analytics(
    limit: int = 20,
) -> dict:
    """Surface quality trends across consultations.

    Returns recent ratings with aggregate statistics for identifying
    quality patterns.

    Args:
        limit: Maximum number of recent ratings to return (default 20).
    """
    limit = max(1, min(100, limit))
    ratings = get_quality_ratings(limit)

    if not ratings:
        return {
            "message": "No quality ratings recorded yet.",
            "ratings": [],
            "aggregate": {},
        }

    # Compute aggregates
    scored = [r for r in ratings if r["rating"] is not None]
    avg_rating = sum(r["rating"] for r in scored) / len(scored) if scored else None

    coverages = [r["concept_coverage"] for r in ratings if r["concept_coverage"] is not None]
    avg_coverage = sum(coverages) / len(coverages) if coverages else None

    pattern_counts = [r["pattern_count"] for r in ratings if r["pattern_count"] is not None]
    avg_patterns = sum(pattern_counts) / len(pattern_counts) if pattern_counts else None

    # Rating distribution
    distribution = {}
    for r in scored:
        distribution[r["rating"]] = distribution.get(r["rating"], 0) + 1

    return {
        "total_ratings": len(ratings),
        "ratings": ratings,
        "aggregate": {
            "avg_rating": round(avg_rating, 2) if avg_rating else None,
            "avg_concept_coverage": round(avg_coverage, 3) if avg_coverage else None,
            "avg_pattern_count": round(avg_patterns, 1) if avg_patterns else None,
            "rating_distribution": distribution,
        },
    }
