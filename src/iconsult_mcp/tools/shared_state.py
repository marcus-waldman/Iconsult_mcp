"""Shared epistemic memory for consultation sessions.

Provides key-value state that subagents can read/write during a consultation,
enabling coordination beyond the append-only step log.
"""

from iconsult_mcp.db import (
    get_consultation,
    log_consultation_step,
    read_shared_state as db_read_state,
    write_shared_state as db_write_state,
)


async def write_state(
    consultation_id: str,
    key: str,
    value: object,
) -> dict:
    """Write a key-value pair to consultation shared state.

    Upserts: creates or updates the entry. Logs a step to the consultation.

    Args:
        consultation_id: The consultation session ID.
        key: State key (e.g. 'discovered_concepts', 'current_phase').
        value: Any JSON-serializable value.
    """
    if not consultation_id or not consultation_id.strip():
        return {"error": "consultation_id is required"}
    if not key or not key.strip():
        return {"error": "key is required"}

    record = get_consultation(consultation_id)
    if record is None:
        return {"error": f"Consultation '{consultation_id}' not found"}

    db_write_state(consultation_id, key, value)

    log_consultation_step(consultation_id, "state_write", {
        "key": key,
    })

    return {
        "written": True,
        "consultation_id": consultation_id,
        "key": key,
    }


async def read_state(
    consultation_id: str,
    key: str | None = None,
) -> dict:
    """Read shared state from a consultation.

    Args:
        consultation_id: The consultation session ID.
        key: Specific key to read, or None for all entries.
    """
    if not consultation_id or not consultation_id.strip():
        return {"error": "consultation_id is required"}

    record = get_consultation(consultation_id)
    if record is None:
        return {"error": f"Consultation '{consultation_id}' not found"}

    entries = db_read_state(consultation_id, key)

    return {
        "consultation_id": consultation_id,
        "entries": entries,
        "count": len(entries),
    }
