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

    # New category-based structure
    assert "categories" in score
    assert "overall_summary" in score
    assert "gap_analysis" in score
    assert "roadmap" in score
    assert "coverage_warnings" in score

    # Each category has expected fields
    for cat_key, cat in score["categories"].items():
        assert "name" in cat
        assert "rating" in cat
        assert cat["rating"] in ("not_started", "emerging", "established", "mature")
        assert "levels" in cat


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

    # Category ratings should be identical
    for cat_key in scores[0]["categories"]:
        assert scores[0]["categories"][cat_key]["rating"] == scores[1]["categories"][cat_key]["rating"]

    assert scores[0]["overall_summary"] == scores[1]["overall_summary"]


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
    """Gap analysis identifies missing patterns."""
    case = SCORE_CASES[0]

    result = await match_concepts(case["description"], max_results=5)
    cid = consultation_cleanup(result["consultation_id"])

    for pa in case["pattern_assessments"]:
        log_consultation_step(cid, "pattern_assessment", pa)

    score = await score_architecture(cid)

    missing_count = sum(
        1 for pa in case["pattern_assessments"] if pa["status"] == "missing"
    )
    if missing_count > 0:
        assert len(score["gap_analysis"]) > 0, "Should identify gaps when patterns are missing"


@pytest.mark.asyncio
async def test_not_applicable_does_not_block_rating(consultation_cleanup):
    """Patterns marked not_applicable should not block category rating progression."""
    from tests.cases import CASES_BY_ID
    case = CASES_BY_ID["research_bot"]

    result = await match_concepts(case["description"], max_results=5)
    cid = consultation_cleanup(result["consultation_id"])

    for pa in case["pattern_assessments"]:
        log_consultation_step(cid, "pattern_assessment", pa)

    score = await score_architecture(cid)
    assert "error" not in score, score.get("error")

    # N/A should not appear in gap analysis
    gap_ids = [g["pattern_id"] for g in score["gap_analysis"]]
    for pa in case["pattern_assessments"]:
        if pa["status"] == "not_applicable":
            pid = pa["pattern_id"]
            assert pid not in gap_ids, f"N/A pattern {pid} should not appear in gaps"


@pytest.mark.asyncio
async def test_coverage_warnings_for_unassessed_categories(consultation_cleanup):
    """Categories with no assessments should trigger coverage warnings."""
    result = await match_concepts("Simple retry-only system", max_results=3)
    cid = consultation_cleanup(result["consultation_id"])

    # Only assess robustness patterns
    log_consultation_step(cid, "pattern_assessment", {
        "pattern_id": "watchdog_timeout",
        "pattern_name": "Watchdog Timeout",
        "status": "implemented",
        "evidence": "test",
        "maturity_level": 1,
    })

    score = await score_architecture(cid)
    assert "error" not in score

    # Should have warnings for unassessed categories
    assert len(score["coverage_warnings"]) > 0
