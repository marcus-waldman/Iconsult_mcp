"""
Validate subagent response tool for iconsult-mcp.

Deterministic schema validation for subagent JSON responses returned
during scatter-gather graph traversal (step 3 of the consulting workflow).
No LLM calls — pure structural validation.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Required top-level keys and their expected types
_SCHEMA = {
    "concept": str,
    "key_relationships": list,
    "recommendation": str,
    "discovered_ids": list,
}


async def validate_subagent(response: dict[str, Any]) -> dict:
    """Validate a subagent response against the expected schema.

    Args:
        response: The JSON object returned by a graph-analysis subagent.

    Returns:
        Dict with valid (bool), errors (list[str]), and warnings (list[str]).
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Check required keys
    for key, expected_type in _SCHEMA.items():
        if key not in response:
            errors.append(f"Missing required field: '{key}'")
        elif not isinstance(response[key], expected_type):
            errors.append(
                f"Field '{key}' should be {expected_type.__name__}, "
                f"got {type(response[key]).__name__}"
            )

    # Validate discovered_ids entries are strings
    discovered = response.get("discovered_ids", [])
    if isinstance(discovered, list):
        non_str = [i for i, v in enumerate(discovered) if not isinstance(v, str)]
        if non_str:
            errors.append(
                f"discovered_ids entries at indices {non_str} are not strings"
            )
        if len(discovered) == 0:
            warnings.append("discovered_ids is empty — subagent found no new concepts")

    # Validate key_relationships entries
    relationships = response.get("key_relationships", [])
    if isinstance(relationships, list):
        if len(relationships) == 0:
            warnings.append("key_relationships is empty")

    # Check recommendation is non-trivial
    rec = response.get("recommendation", "")
    if isinstance(rec, str) and len(rec.strip()) < 10:
        warnings.append("recommendation is very short (< 10 chars)")

    # Check concept is non-empty
    concept = response.get("concept", "")
    if isinstance(concept, str) and len(concept.strip()) == 0:
        errors.append("concept field is empty")

    valid = len(errors) == 0
    return {
        "valid": valid,
        "errors": errors,
        "warnings": warnings,
        "field_count": len([k for k in _SCHEMA if k in response]),
        "expected_fields": list(_SCHEMA.keys()),
    }
