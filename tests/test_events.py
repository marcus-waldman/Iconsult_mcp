"""Tests for event-driven reactivity (emit_event + get_events)."""

import pytest

from iconsult_mcp.tools.match_concepts import match_concepts
from iconsult_mcp.tools.events import emit_event, get_events

from tests.cases import CASES_BY_ID

FLOW_CASE = CASES_BY_ID["financial_research"]


@pytest.mark.asyncio
async def test_emit_and_get_event(consultation_cleanup):
    """Emit an event and retrieve it."""
    match_result = await match_concepts(FLOW_CASE["description"], max_results=5)
    cid = consultation_cleanup(match_result["consultation_id"])

    emit_result = await emit_event(cid, "gap_found", {"pattern": "auth"})
    assert emit_result["emitted"] is True
    assert emit_result["event_type"] == "gap_found"
    assert "suggestion" in emit_result

    events_result = await get_events(cid)
    assert events_result["count"] >= 1
    event = events_result["events"][-1]
    assert event["event_type"] == "gap_found"
    assert event["data"]["pattern"] == "auth"


@pytest.mark.asyncio
async def test_event_suggestions(consultation_cleanup):
    """Each event type returns a relevant suggestion."""
    match_result = await match_concepts(FLOW_CASE["description"], max_results=5)
    cid = consultation_cleanup(match_result["consultation_id"])

    result = await emit_event(cid, "coverage_threshold_reached")
    assert "scoring" in result["suggestion"].lower() or "synthesis" in result["suggestion"].lower()


@pytest.mark.asyncio
async def test_poll_since_id(consultation_cleanup):
    """Polling with since_id returns only newer events."""
    match_result = await match_concepts(FLOW_CASE["description"], max_results=5)
    cid = consultation_cleanup(match_result["consultation_id"])

    r1 = await emit_event(cid, "gap_found", {"n": 1})
    r2 = await emit_event(cid, "pattern_assessed", {"n": 2})

    events_result = await get_events(cid, since_id=r1["event_id"])
    assert events_result["count"] >= 1
    event_ids = [e["id"] for e in events_result["events"]]
    assert r1["event_id"] not in event_ids
    assert r2["event_id"] in event_ids


@pytest.mark.asyncio
async def test_poll_by_type(consultation_cleanup):
    """Polling with event_type filter returns only matching events."""
    match_result = await match_concepts(FLOW_CASE["description"], max_results=5)
    cid = consultation_cleanup(match_result["consultation_id"])

    await emit_event(cid, "gap_found", {"n": 1})
    await emit_event(cid, "pattern_assessed", {"n": 2})

    events_result = await get_events(cid, event_type="gap_found")
    for event in events_result["events"]:
        assert event["event_type"] == "gap_found"


@pytest.mark.asyncio
async def test_invalid_event_type(consultation_cleanup):
    """Emitting an invalid event type returns error."""
    match_result = await match_concepts(FLOW_CASE["description"], max_results=5)
    cid = consultation_cleanup(match_result["consultation_id"])

    result = await emit_event(cid, "invalid_type")
    assert "error" in result


@pytest.mark.asyncio
async def test_emit_event_invalid_consultation():
    """Emitting to a nonexistent consultation returns error."""
    result = await emit_event("nonexistent_id", "gap_found")
    assert "error" in result
