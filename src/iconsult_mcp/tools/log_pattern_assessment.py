"""Log a pattern assessment step to a consultation session."""

from iconsult_mcp.db import log_consultation_step
from iconsult_mcp.tools.rubric_data import (
    normalize_pattern_id,
    get_pattern_indicators,
    get_pattern_category,
    get_pattern_level,
)

VALID_STATUSES = {"implemented", "partial", "missing", "not_applicable"}


async def log_pattern_assessment(
    consultation_id: str,
    pattern_id: str,
    pattern_name: str,
    status: str,
    evidence: str = "",
    maturity_level: int = 1,
    failure_context: dict | None = None,
    category: str = "",
    indicators: list[dict] | None = None,
) -> dict:
    """Log a pattern assessment to a consultation's step log.

    Args:
        consultation_id: The consultation session ID from match_concepts.
        pattern_id: The concept ID of the pattern being assessed.
        pattern_name: Human-readable name of the pattern.
        status: One of "implemented", "partial", "missing", or "not_applicable".
            When indicators are provided and status is not "not_applicable",
            status is auto-computed from indicators.
        evidence: File path or description of what was found.
        maturity_level: Kept for backward compat.
        failure_context: Optional structured failure context for stress test demos.
            Fields: code_refs (list of {file, line, snippet}),
            failure_mode (str), depends_on (list of pattern_ids).
        category: Category key (auto-resolved from rubric if empty).
        indicators: List of indicator assessments.
            Each: {"text": str, "met": bool, "na": bool (optional)}.
            When provided, status is auto-computed unless "not_applicable".
    """
    if not consultation_id or not consultation_id.strip():
        return {"error": "consultation_id is required"}
    if not pattern_id or not pattern_id.strip():
        return {"error": "pattern_id is required"}
    if not pattern_name or not pattern_name.strip():
        return {"error": "pattern_name is required"}

    # Normalise pattern ID
    canonical_pid = normalize_pattern_id(pattern_id)

    # Auto-resolve category from rubric
    if not category:
        category = get_pattern_category(canonical_pid) or ""

    # Auto-resolve level from rubric
    level = get_pattern_level(canonical_pid) or ""

    # Process indicators
    indicator_data = None
    if indicators and isinstance(indicators, list):
        indicator_data = []
        for ind in indicators:
            indicator_data.append({
                "text": str(ind.get("text", "")),
                "met": bool(ind.get("met", False)),
                "na": bool(ind.get("na", False)),
            })

        # Auto-compute status from indicators (unless explicitly not_applicable)
        if status != "not_applicable":
            applicable = [i for i in indicator_data if not i.get("na", False)]
            if not applicable:
                status = "not_applicable"
            elif all(i["met"] for i in applicable):
                status = "implemented"
            else:
                status = "missing"

    # Validate status
    if status not in VALID_STATUSES:
        return {"error": f"status must be one of {sorted(VALID_STATUSES)}, got '{status}'"}

    # Validate indicators against rubric (warn on mismatch)
    warnings = []
    if indicator_data:
        rubric_indicators = get_pattern_indicators(canonical_pid)
        if rubric_indicators:
            rubric_texts = set(rubric_indicators)
            assessed_texts = {i["text"] for i in indicator_data}
            extra = assessed_texts - rubric_texts
            if extra:
                warnings.append(
                    f"Indicators not in rubric: {', '.join(sorted(extra)[:3])}"
                )

    step_data = {
        "pattern_id": canonical_pid,
        "pattern_name": pattern_name,
        "status": status,
        "evidence": evidence,
        "maturity_level": maturity_level,
        "category": category,
        "level": level,
    }

    if indicator_data:
        step_data["indicators"] = indicator_data

    if failure_context and isinstance(failure_context, dict):
        step_data["failure_context"] = failure_context

    log_consultation_step(consultation_id, "pattern_assessment", step_data)

    result = {
        "logged": True,
        "consultation_id": consultation_id,
        "pattern_id": canonical_pid,
        "pattern_name": pattern_name,
        "status": status,
        "category": category,
        "level": level,
    }
    if warnings:
        result["warnings"] = warnings
    return result
