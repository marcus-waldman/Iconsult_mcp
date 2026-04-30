"""
Access policy declarations for iconsult-mcp tools.

MCP stdio is a local subprocess — full bearer-token auth would be theater.
Instead, this module provides declarative capability levels and consultation
ownership validation. Scores as "partial" auth/authz (appropriate for transport).
"""

import logging

from iconsult_mcp.db import get_consultation

logger = logging.getLogger(__name__)

# Tool access levels: read (safe queries), write (mutates state), admin (diagnostic/config)
TOOL_ACCESS = {
    "health_check": "admin",
    "match_concepts": "write",
    "list_books": "read",
    "list_concepts": "read",
    "get_subgraph": "read",
    "ask_book": "read",
    "consultation_report": "read",
    "score_architecture": "read",
    "log_pattern_assessment": "write",
    "validate_subagent": "read",
    "critique_consultation": "read",
    "write_state": "write",
    "read_state": "read",
    "emit_event": "write",
    "get_events": "read",
    "plan_consultation": "write",
    "supervise_consultation": "read",
    "generate_failure_scenarios": "read",
    "generate_implementation_plan": "write",
    "get_implementation_plan": "read",
    "update_plan_step": "write",
}


def get_tool_access_level(tool_name: str) -> str:
    """Return the access level for a tool, defaulting to 'read'."""
    return TOOL_ACCESS.get(tool_name, "read")


def validate_consultation_ownership(consultation_id: str) -> dict:
    """Validate that a consultation exists and is accessible.

    Returns:
        Dict with 'valid' (bool) and optional 'error' (str).
    """
    if not consultation_id or not consultation_id.strip():
        return {"valid": False, "error": "consultation_id is required"}

    record = get_consultation(consultation_id)
    if record is None:
        return {"valid": False, "error": f"Consultation '{consultation_id}' not found"}

    return {"valid": True}
