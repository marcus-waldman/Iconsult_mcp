"""Log a pattern assessment step to a consultation session."""

from iconsult_mcp.db import log_consultation_step

VALID_STATUSES = {"implemented", "partial", "missing"}


async def log_pattern_assessment(
    consultation_id: str,
    pattern_id: str,
    pattern_name: str,
    status: str,
    evidence: str = "",
    maturity_level: int = 1,
) -> dict:
    """Log a pattern assessment to a consultation's step log.

    Args:
        consultation_id: The consultation session ID from match_concepts.
        pattern_id: The concept ID of the pattern being assessed.
        pattern_name: Human-readable name of the pattern.
        status: One of "implemented", "partial", or "missing".
        evidence: File path or description of what was found.
        maturity_level: Assessed maturity level (1-6).
    """
    if not consultation_id or not consultation_id.strip():
        return {"error": "consultation_id is required"}
    if not pattern_id or not pattern_id.strip():
        return {"error": "pattern_id is required"}
    if not pattern_name or not pattern_name.strip():
        return {"error": "pattern_name is required"}
    if status not in VALID_STATUSES:
        return {"error": f"status must be one of {sorted(VALID_STATUSES)}, got '{status}'"}

    maturity_level = max(1, min(6, maturity_level))

    log_consultation_step(consultation_id, "pattern_assessment", {
        "pattern_id": pattern_id,
        "pattern_name": pattern_name,
        "status": status,
        "evidence": evidence,
        "maturity_level": maturity_level,
    })

    return {
        "logged": True,
        "consultation_id": consultation_id,
        "pattern_id": pattern_id,
        "pattern_name": pattern_name,
        "status": status,
    }
