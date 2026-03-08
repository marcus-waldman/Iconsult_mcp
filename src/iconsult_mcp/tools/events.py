"""Event-driven reactivity for consultation sessions.

Provides event emission and polling (MCP stdio can't push).
Tools emit events; orchestrator polls via get_events.
"""

from iconsult_mcp.db import (
    get_consultation,
    emit_consultation_event as db_emit_event,
    get_consultation_events as db_get_events,
)

VALID_EVENT_TYPES = {
    "gap_found",
    "pattern_assessed",
    "coverage_threshold_reached",
    "coverage_dropped",
    "plan_created",
    "state_conflict",
}

# Reactive suggestions per event type
EVENT_SUGGESTIONS = {
    "gap_found": "Consider calling ask_book scoped to the gap concept for remediation guidance.",
    "pattern_assessed": "Run consultation_report to check if coverage thresholds improved.",
    "coverage_threshold_reached": "Coverage is sufficient. Proceed to scoring and synthesis.",
    "coverage_dropped": "Coverage regressed. Review recent state changes and re-assess patterns.",
    "plan_created": "Follow the generated plan steps. Call supervise_consultation for progress tracking.",
    "state_conflict": "Multiple subagents wrote conflicting state. Review shared state and resolve.",
}


async def emit_event(
    consultation_id: str,
    event_type: str,
    data: dict | None = None,
) -> dict:
    """Emit a consultation event and return a reactive suggestion.

    Args:
        consultation_id: The consultation session ID.
        event_type: One of the valid event types.
        data: Optional JSON-serializable event payload.
    """
    if not consultation_id or not consultation_id.strip():
        return {"error": "consultation_id is required"}
    if event_type not in VALID_EVENT_TYPES:
        return {
            "error": f"event_type must be one of {sorted(VALID_EVENT_TYPES)}, got '{event_type}'"
        }

    record = get_consultation(consultation_id)
    if record is None:
        return {"error": f"Consultation '{consultation_id}' not found"}

    event_id = db_emit_event(consultation_id, event_type, data or {})
    suggestion = EVENT_SUGGESTIONS.get(event_type, "")

    return {
        "emitted": True,
        "event_id": event_id,
        "consultation_id": consultation_id,
        "event_type": event_type,
        "suggestion": suggestion,
    }


async def get_events(
    consultation_id: str,
    since_id: int | None = None,
    event_type: str | None = None,
) -> dict:
    """Poll consultation events with optional filters.

    Args:
        consultation_id: The consultation session ID.
        since_id: Only return events with id > since_id.
        event_type: Filter by event type.
    """
    if not consultation_id or not consultation_id.strip():
        return {"error": "consultation_id is required"}
    if event_type is not None and event_type not in VALID_EVENT_TYPES:
        return {
            "error": f"event_type must be one of {sorted(VALID_EVENT_TYPES)}, got '{event_type}'"
        }

    record = get_consultation(consultation_id)
    if record is None:
        return {"error": f"Consultation '{consultation_id}' not found"}

    events = db_get_events(consultation_id, since_id, event_type)

    return {
        "consultation_id": consultation_id,
        "events": events,
        "count": len(events),
    }
