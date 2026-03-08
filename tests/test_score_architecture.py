"""Test score_architecture with synthetic pattern assessments.

Creates a consultation, injects pattern_assessment steps from test cases,
and validates the scoring output structure and determinism.
"""

import pytest

from tests.cases import CASES

from iconsult_mcp.tools.match_concepts import match_concepts
from iconsult_mcp.tools.score_architecture import score_architecture
from iconsult_mcp.db import log_consultation_step


SCORE_CASES = [c for c in CASES if len(c.get("pattern_assessments", [])) >= 3]


@pytest.fixture(params=SCORE_CASES, ids=[c["id"] for c in SCORE_CASES])
def case(request):
    return request.param


@pytest.mark.asyncio
async def test_score_produces_valid_output(case, consultation_cleanup):
    """Score architecture returns all expected sections."""
    result = await match_concepts(case["description"], max_results=5)
    cid = consultation_cleanup(result["consultation_id"])

    # Inject pattern assessments
    for pa in case["pattern_assessments"]:
        log_consultation_step(cid, "pattern_assessment", pa)

    score = await score_architecture(cid)

    assert "error" not in score, score.get("error")
    assert score["consultation_id"] == cid

    # Structure checks
    assert "maturity" in score
    assert "current_level" in score["maturity"]
    assert 0 <= score["maturity"]["current_level"] <= 6

    assert "overall_score" not in score
    assert "dimension_scores" not in score

    assert "pattern_coverage" in score
    assert "gap_analysis" in score
    assert "roadmap" in score

    # Every pattern in coverage details must have goal and phase fields
    for detail in score["pattern_coverage"]["details"]:
        assert "goal" in detail, f"Missing goal for {detail['pattern_id']}"
        assert detail["goal"] in ("implemented", "partial", "missing", "not_applicable")
        assert "phase" in detail, f"Missing phase for {detail['pattern_id']}"


@pytest.mark.asyncio
async def test_score_determinism(consultation_cleanup):
    """Same assessments produce identical scores."""
    case = SCORE_CASES[0]

    scores = []
    for _ in range(2):
        result = await match_concepts(case["description"], max_results=5)
        cid = consultation_cleanup(result["consultation_id"])

        for pa in case["pattern_assessments"]:
            log_consultation_step(cid, "pattern_assessment", pa)

        score = await score_architecture(cid)
        scores.append(score)

    assert scores[0]["maturity"]["current_level"] == scores[1]["maturity"]["current_level"]
    assert scores[0]["pattern_coverage"] == scores[1]["pattern_coverage"]


@pytest.mark.asyncio
async def test_score_empty_consultation_errors(consultation_cleanup):
    """Score with no assessments returns helpful error."""
    result = await match_concepts("empty test project", max_results=5)
    cid = consultation_cleanup(result["consultation_id"])

    score = await score_architecture(cid)
    assert "error" in score
    assert "pattern_assessment" in score["error"].lower() or "pattern assessments" in score["error"].lower()


@pytest.mark.asyncio
async def test_score_gap_analysis_flags_missing(consultation_cleanup):
    """Gap analysis identifies missing patterns needed for next level."""
    case = SCORE_CASES[0]

    result = await match_concepts(case["description"], max_results=5)
    cid = consultation_cleanup(result["consultation_id"])

    for pa in case["pattern_assessments"]:
        log_consultation_step(cid, "pattern_assessment", pa)

    score = await score_architecture(cid)

    if score["maturity"]["current_level"] < 6:
        # There should be gaps identified for the target level
        # (unless the case happens to have everything implemented)
        missing_count = sum(
            1 for pa in case["pattern_assessments"] if pa["status"] == "missing"
        )
        if missing_count > 0:
            assert len(score["gap_analysis"]) > 0 or score["maturity"]["current_level"] > 0, (
                "Should identify gaps when patterns are missing"
            )


@pytest.mark.asyncio
async def test_not_applicable_does_not_block_level(consultation_cleanup):
    """Patterns marked not_applicable should not block maturity level progression."""
    from tests.cases import CASES_BY_ID
    case = CASES_BY_ID["research_bot"]

    result = await match_concepts(case["description"], max_results=5)
    cid = consultation_cleanup(result["consultation_id"])

    for pa in case["pattern_assessments"]:
        log_consultation_step(cid, "pattern_assessment", pa)

    score = await score_architecture(cid)
    assert "error" not in score, score.get("error")

    # research_bot has agent_calls_human as not_applicable — should not block L1
    # It still has watchdog_timeout as missing, so it won't fully pass L1,
    # but the N/A pattern itself should not be counted as a blocker
    l1_details = score["maturity"]["level_details"][1]
    human_pattern = next(
        p for p in l1_details["patterns"] if p["id"] == "agent_calls_human_pattern"
    )
    assert human_pattern["status"] == "not_applicable"

    # N/A should not appear in gap analysis
    gap_ids = [g["pattern_id"] for g in score["gap_analysis"]]
    assert "agent_calls_human_pattern" not in gap_ids

    # N/A count should be tracked
    assert score["pattern_coverage"]["not_applicable"] >= 1


@pytest.mark.asyncio
async def test_not_applicable_goal_preserved(consultation_cleanup):
    """Patterns marked not_applicable should have goal='not_applicable'."""
    from tests.cases import CASES_BY_ID
    case = CASES_BY_ID["research_bot"]

    result = await match_concepts(case["description"], max_results=5)
    cid = consultation_cleanup(result["consultation_id"])

    for pa in case["pattern_assessments"]:
        log_consultation_step(cid, "pattern_assessment", pa)

    score = await score_architecture(cid)

    na_details = [
        d for d in score["pattern_coverage"]["details"]
        if d["status"] == "not_applicable"
    ]
    assert len(na_details) >= 1
    for d in na_details:
        assert d["goal"] == "not_applicable"
        assert d["priority"] == "---"


@pytest.mark.asyncio
async def test_phase_field_assigned_correctly(consultation_cleanup):
    """Phase field should align patterns with their implementation roadmap phase."""
    from tests.cases import CASES_BY_ID
    case = CASES_BY_ID["research_bot"]

    result = await match_concepts(case["description"], max_results=5)
    cid = consultation_cleanup(result["consultation_id"])

    for pa in case["pattern_assessments"]:
        log_consultation_step(cid, "pattern_assessment", pa)

    score = await score_architecture(cid)
    current = score["maturity"]["current_level"]

    for detail in score["pattern_coverage"]["details"]:
        if detail["status"] in ("implemented", "not_applicable"):
            # Already done patterns have no phase
            assert detail["phase"] is None, (
                f"{detail['pattern_name']} is {detail['status']} but has phase={detail['phase']}"
            )
        elif detail["phase"] is not None:
            # Phase should be level - current_level (1-based offset)
            expected_phase = detail["maturity_level"] - current
            assert detail["phase"] == expected_phase, (
                f"{detail['pattern_name']} at L{detail['maturity_level']} should be phase "
                f"{expected_phase}, got {detail['phase']}"
            )
