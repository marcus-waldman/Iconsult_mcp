"""Blackboard Knowledge Hub — typed, versioned fact store for scatter-gather coordination.

Replaces last-write-wins key-value state with append-only facts that support
conflict detection, confidence scores, and TTL expiry.
"""

from iconsult_mcp.db import (
    get_consultation,
    assert_blackboard_fact,
    query_blackboard_facts,
    get_fact_conflicts,
    get_convergence_status,
    log_consultation_step,
)


async def assert_fact(
    consultation_id: str,
    fact_type: str,
    key: str,
    value: object,
    confidence: float = 1.0,
    agent_id: str | None = None,
    ttl_seconds: int | None = None,
) -> dict:
    """Assert a fact on the blackboard (append-only, never overwrites).

    Facts are versioned per (key, agent_id). Multiple agents can assert
    different values for the same key — use query_facts with detect_conflicts
    to find disagreements.

    Args:
        consultation_id: The consultation session.
        fact_type: Category of fact (e.g., 'concept_finding', 'pattern_status',
            'recommendation', 'conflict_marker').
        key: Fact key (e.g., a concept ID or pattern ID).
        value: Arbitrary JSON-serializable value.
        confidence: Confidence score 0.0-1.0 (default 1.0).
        agent_id: Identifier of the subagent asserting this fact.
        ttl_seconds: Optional time-to-live in seconds.
    """
    if not consultation_id or not consultation_id.strip():
        return {"error": "consultation_id is required"}
    if not fact_type or not fact_type.strip():
        return {"error": "fact_type is required"}
    if not key or not key.strip():
        return {"error": "key is required"}

    record = get_consultation(consultation_id)
    if not record:
        return {"error": f"Consultation '{consultation_id}' not found"}

    confidence = max(0.0, min(1.0, confidence))

    fact_id = assert_blackboard_fact(
        consultation_id=consultation_id,
        fact_type=fact_type,
        key=key,
        value=value,
        confidence=confidence,
        agent_id=agent_id,
        ttl_seconds=ttl_seconds,
    )

    # Log step
    log_consultation_step(consultation_id, "blackboard_assert", {
        "fact_id": fact_id,
        "fact_type": fact_type,
        "key": key,
        "agent_id": agent_id,
        "confidence": confidence,
    })

    return {
        "consultation_id": consultation_id,
        "fact_id": fact_id,
        "fact_type": fact_type,
        "key": key,
        "agent_id": agent_id,
        "confidence": confidence,
    }


async def query_facts(
    consultation_id: str,
    fact_type: str | None = None,
    key: str | None = None,
    min_confidence: float | None = None,
    detect_conflicts: bool = False,
) -> dict:
    """Query facts from the blackboard.

    Args:
        consultation_id: The consultation session.
        fact_type: Filter by fact type (optional).
        key: Filter by key (optional).
        min_confidence: Minimum confidence threshold (optional).
        detect_conflicts: If True, include conflict detection and convergence summary.
    """
    if not consultation_id or not consultation_id.strip():
        return {"error": "consultation_id is required"}

    record = get_consultation(consultation_id)
    if not record:
        return {"error": f"Consultation '{consultation_id}' not found"}

    facts = query_blackboard_facts(
        consultation_id=consultation_id,
        fact_type=fact_type,
        key=key,
        min_confidence=min_confidence,
    )

    result: dict = {
        "consultation_id": consultation_id,
        "fact_count": len(facts),
        "facts": facts,
    }

    if detect_conflicts:
        if key:
            # Single key conflict check
            conflicts = get_fact_conflicts(consultation_id, key)
            result["conflicts"] = conflicts
            result["has_conflicts"] = bool(conflicts)
        else:
            # Full convergence check
            convergence = get_convergence_status(consultation_id)
            result["convergence"] = convergence

    return result
