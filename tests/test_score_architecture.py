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

    assert "overall_score" in score
    assert 0 <= score["overall_score"] <= 100

    assert "dimension_scores" in score
    for dim in ["Robustness", "Coordination", "Compliance", "User Interaction", "Agent Capabilities"]:
        assert dim in score["dimension_scores"], f"Missing dimension: {dim}"
        assert "score" in score["dimension_scores"][dim]

    assert "pattern_coverage" in score
    assert "gap_analysis" in score
    assert "roadmap" in score


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

    assert scores[0]["overall_score"] == scores[1]["overall_score"]
    assert scores[0]["maturity"]["current_level"] == scores[1]["maturity"]["current_level"]

    for dim in scores[0]["dimension_scores"]:
        assert scores[0]["dimension_scores"][dim]["score"] == scores[1]["dimension_scores"][dim]["score"]


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
