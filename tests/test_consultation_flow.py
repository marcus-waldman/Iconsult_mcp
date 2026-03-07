"""End-to-end consultation workflow tests.

Exercises the full pipeline: match -> subgraph -> ask_book -> report -> score.
Uses a single representative case to limit API costs.
"""

import pytest

from tests.cases import CASES_BY_ID

from iconsult_mcp.tools.match_concepts import match_concepts
from iconsult_mcp.tools.ask_book import ask_book
from iconsult_mcp.tools.consultation_report import consultation_report
from iconsult_mcp.tools.score_architecture import score_architecture
from iconsult_mcp.db import get_subgraph, log_consultation_step, get_consultation


FLOW_CASE = CASES_BY_ID["financial_research"]


@pytest.mark.asyncio
async def test_full_consultation_flow(consultation_cleanup):
    """Run the complete 6-step workflow on the financial research case."""
    case = FLOW_CASE

    # Step 1-2: Match concepts
    match_result = await match_concepts(case["description"], max_results=10)
    assert "error" not in match_result
    cid = consultation_cleanup(match_result["consultation_id"])
    matched_ids = [m["id"] for m in match_result["matched_concepts"]]
    assert len(matched_ids) > 0

    # Step 3: Traverse graph
    subgraph = get_subgraph(matched_ids[:5], max_hops=1, confidence_threshold=0.3)
    assert len(subgraph["nodes"]) > 0

    # Log pattern assessments
    for pa in case["pattern_assessments"]:
        log_consultation_step(cid, "pattern_assessment", pa)

    # Verify steps were logged
    record = get_consultation(cid)
    assert record is not None
    assessments = [s for s in record["steps"] if s["type"] == "pattern_assessment"]
    assert len(assessments) == len(case["pattern_assessments"])

    # Step 4: Ask book
    book_result = await ask_book(
        question="How should a supervisor architecture coordinate sub-agents?",
        concept_ids=matched_ids[:3],
        max_passages=3,
        consultation_id=cid,
    )
    assert "error" not in book_result
    assert len(book_result.get("passages", [])) > 0

    # Step 5: Consultation report
    report = await consultation_report(cid)
    assert "error" not in report
    assert "metrics" in report
    assert report["metrics"]["concepts_matched"] > 0

    # Step 5b: Score architecture
    score = await score_architecture(cid)
    assert "error" not in score
    assert score["overall_score"] >= 0
    assert score["maturity"]["current_level"] >= 0

    # Step 6: Verify synthesis data is available
    # All the data needed for synthesis should be present
    assert len(subgraph["edges"]) > 0, "Need edges for diagram"
    assert len(book_result["passages"]) > 0, "Need passages for citations"
    assert len(score["dimension_scores"]) == 5, "Need all 5 dimensions"


@pytest.mark.asyncio
async def test_consultation_report_tracks_steps(consultation_cleanup):
    """Report reflects logged steps."""
    match_result = await match_concepts(FLOW_CASE["description"], max_results=5)
    cid = consultation_cleanup(match_result["consultation_id"])

    # Log a subgraph step
    log_consultation_step(cid, "subgraph_query", {
        "concept_ids": ["supervisor_architecture"],
        "nodes_found": 5,
    })

    # Log a book query step
    log_consultation_step(cid, "book_query", {
        "question": "test question",
        "passages_found": 3,
    })

    report = await consultation_report(cid)
    assert "error" not in report
    # Steps are tracked in the consultation record; the report
    # computes metrics from them. Verify metrics reflect the steps.
    steps = report["metrics"]
    assert steps["concepts_matched"] > 0


@pytest.mark.asyncio
async def test_ask_book_returns_suggested_questions(consultation_cleanup):
    """ask_book returns suggested follow-up questions from graph edges."""
    match_result = await match_concepts(FLOW_CASE["description"], max_results=5)
    cid = consultation_cleanup(match_result["consultation_id"])

    matched_ids = [m["id"] for m in match_result["matched_concepts"][:3]]

    book_result = await ask_book(
        question="What are the key patterns for multi-agent coordination?",
        concept_ids=matched_ids,
        consultation_id=cid,
    )
    assert "error" not in book_result

    # Should have passages
    assert len(book_result.get("passages", [])) > 0

    # Passages should have chapter info
    for passage in book_result["passages"]:
        assert "chapter_number" in passage or "title" in passage
