"""Tests for consultation supervisor."""

import pytest

from iconsult_mcp.tools.match_concepts import match_concepts
from iconsult_mcp.tools.supervise_consultation import (
    supervise_consultation,
    _compute_progress,
    WORKFLOW_PHASES,
)
from iconsult_mcp.db import log_consultation_step, get_consultation

from tests.cases import CASES_BY_ID

FLOW_CASE = CASES_BY_ID["financial_research"]


@pytest.mark.asyncio
async def test_supervise_empty_consultation(consultation_cleanup):
    """A fresh consultation has low progress and suggests planning."""
    match_result = await match_concepts(FLOW_CASE["description"], max_results=5)
    cid = consultation_cleanup(match_result["consultation_id"])

    result = await supervise_consultation(cid)
    assert "error" not in result
    assert result["progress"]["progress_percent"] < 50
    # Should suggest plan as next action (match is already done via match_concepts
    # but we don't log a "match" step type — so the supervisor may suggest match or plan)
    assert result["next_action"]["tool"] is not None


@pytest.mark.asyncio
async def test_supervise_partial_progress(consultation_cleanup):
    """After some steps, progress increases and next action advances."""
    match_result = await match_concepts(FLOW_CASE["description"], max_results=5)
    cid = consultation_cleanup(match_result["consultation_id"])

    # Log a plan step and a subgraph step
    log_consultation_step(cid, "plan_created", {"complexity": {"level": "simple"}})
    log_consultation_step(cid, "subgraph_query", {"concept_ids": ["c1"]})

    result = await supervise_consultation(cid)
    assert "error" not in result
    assert "plan" in result["progress"]["completed"]
    assert "traverse" in result["progress"]["completed"]
    assert result["progress"]["progress_percent"] > 0


@pytest.mark.asyncio
async def test_supervise_complete_workflow(consultation_cleanup):
    """After all phases, progress is 100% and action is complete."""
    match_result = await match_concepts(FLOW_CASE["description"], max_results=5)
    cid = consultation_cleanup(match_result["consultation_id"])

    # Log all phase step types
    for phase in WORKFLOW_PHASES:
        step_type = phase["step_types"][0]
        log_consultation_step(cid, step_type, {"test": True})

    result = await supervise_consultation(cid)
    assert result["progress"]["progress_percent"] == 100
    assert result["progress"]["current_phase"] == "done"
    assert result["next_action"]["action"] == "complete"


@pytest.mark.asyncio
async def test_supervise_invalid_consultation():
    """Supervising a nonexistent consultation returns error."""
    result = await supervise_consultation("nonexistent_id")
    assert "error" in result


@pytest.mark.asyncio
async def test_supervise_includes_events(consultation_cleanup):
    """Supervisor includes recent event alerts."""
    match_result = await match_concepts(FLOW_CASE["description"], max_results=5)
    cid = consultation_cleanup(match_result["consultation_id"])

    # Emit an event
    from iconsult_mcp.tools.events import emit_event
    await emit_event(cid, "gap_found", {"pattern": "auth"})

    result = await supervise_consultation(cid)
    assert len(result["event_alerts"]) >= 1


@pytest.mark.asyncio
async def test_supervise_includes_shared_state(consultation_cleanup):
    """Supervisor includes shared state entries."""
    match_result = await match_concepts(FLOW_CASE["description"], max_results=5)
    cid = consultation_cleanup(match_result["consultation_id"])

    from iconsult_mcp.tools.shared_state import write_state
    await write_state(cid, "test_key", "test_value")

    result = await supervise_consultation(cid)
    assert len(result["shared_state_entries"]) >= 1
