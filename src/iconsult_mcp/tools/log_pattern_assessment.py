"""Log a pattern assessment step to a consultation session."""

from iconsult_mcp.db import log_consultation_step

VALID_STATUSES = {"implemented", "partial", "missing", "not_applicable"}


async def log_pattern_assessment(
    consultation_id: str,
    pattern_id: str,
    pattern_name: str,
    status: str,
    evidence: str = "",
    maturity_level: int = 1,
    failure_context: dict | None = None,
) -> dict:
    """Log a pattern assessment to a consultation's step log.

    Args:
        consultation_id: The consultation session ID from match_concepts.
        pattern_id: The concept ID of the pattern being assessed.
        pattern_name: Human-readable name of the pattern.
        status: One of "implemented", "partial", "missing", or "not_applicable".
        evidence: File path or description of what was found.
        maturity_level: Assessed maturity level (1-6).
        failure_context: Optional structured failure context for stress test demos.
            Fields: code_refs (list of {file, line, snippet}),
            failure_mode (str), depends_on (list of pattern_ids).
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

    step_data = {
        "pattern_id": pattern_id,
        "pattern_name": pattern_name,
        "status": status,
        "evidence": evidence,
        "maturity_level": maturity_level,
    }

    if failure_context and isinstance(failure_context, dict):
        step_data["failure_context"] = failure_context

    log_consultation_step(consultation_id, "pattern_assessment", step_data)

    return {
        "logged": True,
        "consultation_id": consultation_id,
        "pattern_id": pattern_id,
        "pattern_name": pattern_name,
        "status": status,
    }
