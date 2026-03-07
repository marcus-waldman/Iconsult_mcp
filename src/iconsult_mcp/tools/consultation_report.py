"""Coverage evaluation, fidelity auditing, and cross-session comparison."""

from iconsult_mcp.db import get_consultation, get_consultations_by_fingerprint

ALL_RELATIONSHIP_TYPES = {
    "uses", "component_of", "extends", "specializes",
    "alternative_to", "requires", "precedes", "enables",
    "conflicts_with", "complements",
}

CRITICAL_EDGE_TYPES = {"requires", "conflicts_with"}


async def consultation_report(
    consultation_id: str,
    compare_to: str | None = None,
) -> dict:
    """Compute coverage metrics for a consultation session.

    Args:
        consultation_id: The consultation to evaluate.
        compare_to: Optional second consultation ID to diff against.
    """
    record = get_consultation(consultation_id)
    if not record:
        return {"error": f"Consultation '{consultation_id}' not found"}

    metrics = _compute_metrics(record)

    result = {
        "consultation_id": consultation_id,
        "project_fingerprint": record["project_fingerprint"],
        "created_at": record["created_at"],
        "metrics": metrics,
    }

    if compare_to:
        other = get_consultation(compare_to)
        if not other:
            result["comparison_error"] = f"Consultation '{compare_to}' not found"
        else:
            result["comparison"] = _compare(record, other)

    return result


def _compute_metrics(record: dict) -> dict:
    matched_ids = set(record["matched_concept_ids"])
    steps = record["steps"]

    # Concepts explored via get_subgraph
    explored_seeds = set()
    discovered_ids = set()
    rel_types_seen = set()
    for step in steps:
        if step.get("type") == "get_subgraph":
            explored_seeds.update(step.get("seed_concept_ids", []))
            discovered_ids.update(step.get("discovered_concept_ids", []))
            rel_types_seen.update(step.get("relationship_types_seen", []))

    # Concept coverage
    explored_matched = matched_ids & explored_seeds
    concept_coverage = len(explored_matched) / len(matched_ids) if matched_ids else 0.0

    # Relationship type coverage
    rel_type_coverage = len(rel_types_seen & ALL_RELATIONSHIP_TYPES) / len(ALL_RELATIONSHIP_TYPES)

    # Passage diversity (chapters retrieved via ask_book)
    chapters_seen = set()
    questions_asked = []
    sections_returned = set()
    for step in steps:
        if step.get("type") == "ask_book":
            chapters_seen.update(step.get("chapters_seen", []))
            questions_asked.append(step.get("question", ""))
            sections_returned.update(step.get("sections_returned", []))

    # Prerequisite/conflict check
    critical_checked = bool(rel_types_seen & CRITICAL_EDGE_TYPES)

    # Gaps
    unexplored_concepts = [cid for cid in matched_ids if cid not in explored_seeds]
    missing_rel_types = sorted(ALL_RELATIONSHIP_TYPES - rel_types_seen)

    return {
        "concept_coverage": round(concept_coverage, 3),
        "concepts_matched": len(matched_ids),
        "concepts_explored": len(explored_matched),
        "concepts_unexplored": unexplored_concepts,
        "relationship_type_coverage": round(rel_type_coverage, 3),
        "relationship_types_seen": sorted(rel_types_seen),
        "relationship_types_missing": missing_rel_types,
        "passage_diversity": {
            "chapters_seen": sorted(chapters_seen),
            "chapter_count": len(chapters_seen),
            "questions_asked": len(questions_asked),
            "sections_returned": len(sections_returned),
        },
        "critical_edges_checked": critical_checked,
        "discovered_concept_count": len(discovered_ids),
    }


def _compare(a: dict, b: dict) -> dict:
    a_metrics = _compute_metrics(a)
    b_metrics = _compute_metrics(b)

    a_concepts = set(a["matched_concept_ids"])
    b_concepts = set(b["matched_concept_ids"])

    a_rel_types = set(a_metrics["relationship_types_seen"])
    b_rel_types = set(b_metrics["relationship_types_seen"])

    return {
        "same_fingerprint": a["project_fingerprint"] == b["project_fingerprint"],
        "concept_overlap": {
            "shared": sorted(a_concepts & b_concepts),
            "only_in_first": sorted(a_concepts - b_concepts),
            "only_in_second": sorted(b_concepts - a_concepts),
        },
        "coverage_delta": {
            "concept_coverage": round(a_metrics["concept_coverage"] - b_metrics["concept_coverage"], 3),
            "rel_type_coverage": round(a_metrics["relationship_type_coverage"] - b_metrics["relationship_type_coverage"], 3),
        },
        "relationship_types": {
            "only_in_first": sorted(a_rel_types - b_rel_types),
            "only_in_second": sorted(b_rel_types - a_rel_types),
        },
        "first": {"id": a["id"], "created_at": a["created_at"]},
        "second": {"id": b["id"], "created_at": b["created_at"]},
    }
