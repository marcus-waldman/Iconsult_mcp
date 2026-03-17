"""Test pattern ID alias resolution between MATURITY_MODEL IDs and KG concept IDs.

Verifies that assessments logged with either ID convention are found by the other,
and that maturity scoring computes correctly regardless of which IDs are used.
"""

import pytest

from iconsult_mcp.tools.match_concepts import match_concepts
from iconsult_mcp.tools.score_architecture import (
    MATURITY_MODEL,
    _PATTERN_ID_ALIASES,
    _PATTERN_ID_ALIAS_COMBINED,
    _get_pattern_assessments,
    _compute_maturity_level,
    normalize_pattern_id,
)
from iconsult_mcp.tools.failure_scenarios import FAILURE_CHAIN, PATTERN_FAILURE_TEMPLATES
from iconsult_mcp.db import log_consultation_step


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_record_with_assessments(steps: list[dict]) -> dict:
    """Build a fake consultation record with pattern_assessment steps."""
    return {"steps": [{"type": "pattern_assessment", **s} for s in steps]}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_kg_id_found_by_maturity_model_id():
    """Assessment logged with a KG ID is accessible via the MATURITY_MODEL ID."""
    record = _make_record_with_assessments([
        {"pattern_id": "single_agent_baseline", "status": "implemented", "evidence": "test"},
    ])
    assessments = _get_pattern_assessments(record)

    # Accessible by original KG ID
    assert "single_agent_baseline" in assessments
    # Also accessible by MATURITY_MODEL ID
    assert "single_agent_baseline_pattern" in assessments
    # Same object
    assert assessments["single_agent_baseline"] is assessments["single_agent_baseline_pattern"]


def test_maturity_model_id_found_by_kg_id():
    """Assessment logged with a MATURITY_MODEL ID is accessible via the KG ID."""
    record = _make_record_with_assessments([
        {"pattern_id": "adaptive_retry_pattern", "status": "implemented", "evidence": "test"},
    ])
    assessments = _get_pattern_assessments(record)

    assert "adaptive_retry_pattern" in assessments
    assert "simple_retry" in assessments
    assert assessments["adaptive_retry_pattern"] is assessments["simple_retry"]


def test_all_aliases_are_bidirectional():
    """Every alias in the forward map has a corresponding reverse entry."""
    for mm_id, kg_id in _PATTERN_ID_ALIASES.items():
        assert _PATTERN_ID_ALIAS_COMBINED.get(mm_id) == kg_id
        assert _PATTERN_ID_ALIAS_COMBINED.get(kg_id) == mm_id


def test_normalize_pattern_id_kg_to_maturity():
    """normalize_pattern_id maps KG IDs to MATURITY_MODEL IDs."""
    assert normalize_pattern_id("simple_retry") == "adaptive_retry_pattern"
    assert normalize_pattern_id("function_calling") == "function_calling_pattern"
    assert normalize_pattern_id("react_reflexion") == "structured_reasoning_and_self"


def test_normalize_pattern_id_maturity_unchanged():
    """normalize_pattern_id returns MATURITY_MODEL IDs unchanged."""
    assert normalize_pattern_id("adaptive_retry_pattern") == "adaptive_retry_pattern"
    assert normalize_pattern_id("supervisor_architecture") == "supervisor_architecture"


def test_normalize_pattern_id_unknown_unchanged():
    """normalize_pattern_id returns unknown IDs unchanged."""
    assert normalize_pattern_id("totally_unknown") == "totally_unknown"


def test_compute_maturity_level_with_kg_ids():
    """_compute_maturity_level correctly scores L1 when assessments use KG IDs."""
    record = _make_record_with_assessments([
        {"pattern_id": "single_agent_baseline", "status": "implemented"},
        {"pattern_id": "function_calling", "status": "implemented"},
        {"pattern_id": "watchdog_timeout", "status": "implemented"},
        {"pattern_id": "agent_calls_human", "status": "implemented"},
    ])
    assessments = _get_pattern_assessments(record)
    maturity = _compute_maturity_level(assessments)

    assert maturity["current_level"] >= 1, (
        f"Expected L1+, got L{maturity['current_level']}. "
        f"This is the core bug: KG IDs must resolve to MATURITY_MODEL IDs."
    )


def test_compute_maturity_level_with_mixed_ids():
    """Maturity computed correctly when some assessments use KG IDs and some use MATURITY_MODEL IDs."""
    record = _make_record_with_assessments([
        # KG IDs
        {"pattern_id": "single_agent_baseline", "status": "implemented"},
        {"pattern_id": "function_calling", "status": "implemented"},
        # MATURITY_MODEL IDs
        {"pattern_id": "watchdog_timeout_pattern", "status": "implemented"},
        {"pattern_id": "agent_calls_human_pattern", "status": "implemented"},
    ])
    assessments = _get_pattern_assessments(record)
    maturity = _compute_maturity_level(assessments)

    assert maturity["current_level"] >= 1


def test_failure_chain_ids_resolvable():
    """FAILURE_CHAIN pattern IDs that are in MATURITY_MODEL are resolvable via alias map."""
    # Collect all MATURITY_MODEL IDs
    all_mm_ids = set()
    for patterns in MATURITY_MODEL.values():
        for p in patterns:
            all_mm_ids.add(p["id"])

    for link in FAILURE_CHAIN:
        pid = link["pattern_id"]
        # Only check patterns that are in MATURITY_MODEL (some chain patterns
        # like auto_healing_pattern are standalone resilience patterns)
        if pid not in all_mm_ids:
            continue
        alias = _PATTERN_ID_ALIAS_COMBINED.get(pid)
        found = pid in PATTERN_FAILURE_TEMPLATES or (alias and alias in PATTERN_FAILURE_TEMPLATES)
        assert found, (
            f"FAILURE_CHAIN pattern_id '{pid}' not in PATTERN_FAILURE_TEMPLATES "
            f"(alias: {alias})"
        )


def test_maturity_model_ids_have_failure_templates():
    """All MATURITY_MODEL IDs have PATTERN_FAILURE_TEMPLATES entries (directly or via alias)."""
    for level, patterns in MATURITY_MODEL.items():
        for p in patterns:
            pid = p["id"]
            alias = _PATTERN_ID_ALIAS_COMBINED.get(pid)
            found = pid in PATTERN_FAILURE_TEMPLATES or (alias and alias in PATTERN_FAILURE_TEMPLATES)
            assert found, (
                f"MATURITY_MODEL L{level} pattern '{pid}' has no PATTERN_FAILURE_TEMPLATES entry "
                f"(alias: {alias})"
            )


@pytest.mark.asyncio
async def test_score_with_kg_ids_integration(consultation_cleanup):
    """End-to-end: score_architecture works when assessments use KG IDs."""
    from iconsult_mcp.tools.score_architecture import score_architecture

    result = await match_concepts("Simple single-agent chatbot", max_results=3)
    cid = consultation_cleanup(result["consultation_id"])

    # Log L1 assessments with KG IDs
    for kg_id in ["single_agent_baseline", "function_calling", "watchdog_timeout", "agent_calls_human"]:
        log_consultation_step(cid, "pattern_assessment", {
            "pattern_id": kg_id,
            "pattern_name": kg_id,
            "status": "implemented",
            "evidence": "test",
            "maturity_level": 1,
        })

    score = await score_architecture(cid)

    assert "error" not in score, score.get("error")
    assert score["maturity"]["current_level"] >= 1, (
        f"Expected L1+ with KG IDs, got L{score['maturity']['current_level']}"
    )
