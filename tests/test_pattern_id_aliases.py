"""Test pattern ID alias resolution between old/KG IDs and rubric IDs.

Verifies that assessments logged with any ID convention are found by the
scoring system, and that category ratings compute correctly.
"""

import pytest

from iconsult_mcp.tools.match_concepts import match_concepts
from iconsult_mcp.tools.rubric_data import (
    RUBRIC,
    ALL_PATTERN_IDS,
    _PATTERN_ID_ALIASES,
    _PATTERN_ID_ALIAS_COMBINED,
    normalize_pattern_id,
)
from iconsult_mcp.tools.score_architecture import (
    _get_pattern_assessments,
    _compute_category_ratings,
    _is_pattern_met,
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


def test_old_id_resolves_to_rubric_id():
    """Old MATURITY_MODEL IDs resolve to canonical rubric IDs."""
    assert normalize_pattern_id("watchdog_timeout_pattern") == "watchdog_timeout"
    assert normalize_pattern_id("agent_calls_human_pattern") == "agent_calls_human"
    assert normalize_pattern_id("agent_authentication_and_authorization") == "agent_auth_and_authz"
    assert normalize_pattern_id("consensus_pattern") == "consensus_and_negotiation"
    assert normalize_pattern_id("majority_voting_pattern") == "majority_voting"


def test_fcot_pattern_anchors_to_fractal_cot_embedding():
    """Arsanjani's `fcot_pattern` concept ID resolves to the rubric pattern.

    Without this alias the multi-book canonical layer (Phase 3c) sees
    arsanjani's FCoT cluster fall into informational_only even though
    Self-Correction and Structured Reasoning (sibling FCoT siblings) DO
    anchor correctly. Companion to `structured_reasoning_and_self` and
    `self_correction_pattern` aliases.
    """
    assert normalize_pattern_id("fcot_pattern") == "fractal_cot_embedding"
    assert normalize_pattern_id("arsanjani_2026__fcot_pattern") == "fractal_cot_embedding"


def test_rubric_id_unchanged():
    """Rubric IDs are returned unchanged by normalize_pattern_id."""
    assert normalize_pattern_id("watchdog_timeout") == "watchdog_timeout"
    assert normalize_pattern_id("supervisor_architecture") == "supervisor_architecture"
    assert normalize_pattern_id("simple_retry") == "simple_retry"


def test_unknown_id_unchanged():
    """Unknown IDs are returned unchanged."""
    assert normalize_pattern_id("totally_unknown") == "totally_unknown"


def test_assessment_found_by_old_id():
    """Assessment logged with old ID is accessible via canonical rubric ID."""
    record = _make_record_with_assessments([
        {"pattern_id": "watchdog_timeout_pattern", "status": "implemented", "evidence": "test"},
    ])
    assessments = _get_pattern_assessments(record)

    # Accessible by canonical rubric ID
    assert "watchdog_timeout" in assessments


def test_assessment_found_by_rubric_id():
    """Assessment logged with rubric ID is accessible directly."""
    record = _make_record_with_assessments([
        {"pattern_id": "watchdog_timeout", "status": "implemented", "evidence": "test"},
    ])
    assessments = _get_pattern_assessments(record)
    assert "watchdog_timeout" in assessments


def test_category_ratings_with_old_ids():
    """Category ratings compute correctly when assessments use old IDs."""
    record = _make_record_with_assessments([
        {"pattern_id": "watchdog_timeout_pattern", "status": "implemented"},
        {"pattern_id": "adaptive_retry_pattern", "status": "implemented"},
    ])
    assessments = _get_pattern_assessments(record)
    ratings = _compute_category_ratings(assessments)

    # Robustness should show at least emerging
    assert ratings["robustness"]["rating"] in ("emerging", "established", "mature")


def test_category_ratings_with_rubric_ids():
    """Category ratings compute correctly with rubric IDs."""
    record = _make_record_with_assessments([
        {"pattern_id": "watchdog_timeout", "status": "implemented"},
        {"pattern_id": "simple_retry", "status": "implemented"},
    ])
    assessments = _get_pattern_assessments(record)
    ratings = _compute_category_ratings(assessments)

    # Both basic robustness patterns met → at least established
    assert ratings["robustness"]["rating"] in ("established", "mature")


def test_failure_chain_ids_are_valid_rubric_ids():
    """FAILURE_CHAIN pattern IDs are valid rubric IDs or resolvable via aliases."""
    from iconsult_mcp.tools.rubric_data import ALL_PATTERN_IDS, _PATTERN_ID_ALIAS_COMBINED
    for link in FAILURE_CHAIN:
        pid = link["pattern_id"]
        alias = _PATTERN_ID_ALIAS_COMBINED.get(pid, pid)
        in_rubric = pid in ALL_PATTERN_IDS or alias in ALL_PATTERN_IDS
        assert in_rubric, (
            f"FAILURE_CHAIN pattern_id '{pid}' (alias: {alias}) not in rubric"
        )


def test_all_rubric_pattern_ids_unique():
    """All pattern IDs across all categories are unique."""
    seen = set()
    for cat in RUBRIC.values():
        for level_patterns in cat["levels"].values():
            for p in level_patterns:
                assert p["id"] not in seen, f"Duplicate pattern ID: {p['id']}"
                seen.add(p["id"])


def test_all_rubric_patterns_have_indicators():
    """Every pattern in the rubric has 2-5 indicators."""
    for cat_key, cat in RUBRIC.items():
        for level_name, level_patterns in cat["levels"].items():
            for p in level_patterns:
                inds = p.get("indicators", [])
                assert 2 <= len(inds) <= 5, (
                    f"{cat_key}/{level_name}/{p['id']} has {len(inds)} indicators "
                    f"(expected 2-5)"
                )


@pytest.mark.asyncio
async def test_score_with_old_ids_integration(consultation_cleanup):
    """End-to-end: score_architecture works when assessments use old IDs."""
    from iconsult_mcp.tools.score_architecture import score_architecture

    result = await match_concepts("Simple single-agent chatbot", max_results=3)
    cid = consultation_cleanup(result["consultation_id"])

    # Log assessments with old IDs
    for old_id in ["watchdog_timeout_pattern", "agent_calls_human_pattern"]:
        log_consultation_step(cid, "pattern_assessment", {
            "pattern_id": old_id,
            "pattern_name": old_id,
            "status": "implemented",
            "evidence": "test",
            "maturity_level": 1,
        })

    score = await score_architecture(cid)
    assert "error" not in score, score.get("error")
    # Should have assessed some categories
    assert score["overall_summary"]["total_assessed"] > 0
