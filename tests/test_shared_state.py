"""Tests for shared epistemic memory (write_state + read_state)."""

import pytest

from iconsult_mcp.tools.match_concepts import match_concepts
from iconsult_mcp.tools.shared_state import write_state, read_state

from tests.cases import CASES_BY_ID

FLOW_CASE = CASES_BY_ID["financial_research"]


@pytest.mark.asyncio
async def test_write_and_read_state(consultation_cleanup):
    """Write a key-value pair and read it back."""
    match_result = await match_concepts(FLOW_CASE["description"], max_results=5)
    cid = consultation_cleanup(match_result["consultation_id"])

    result = await write_state(cid, "discovered_concepts", ["c1", "c2"])
    assert result["written"] is True
    assert result["key"] == "discovered_concepts"

    read_result = await read_state(cid, "discovered_concepts")
    assert read_result["count"] == 1
    assert read_result["entries"][0]["value"] == ["c1", "c2"]


@pytest.mark.asyncio
async def test_upsert_state(consultation_cleanup):
    """Writing the same key again updates the value."""
    match_result = await match_concepts(FLOW_CASE["description"], max_results=5)
    cid = consultation_cleanup(match_result["consultation_id"])

    await write_state(cid, "phase", "traverse")
    await write_state(cid, "phase", "assess")

    read_result = await read_state(cid, "phase")
    assert read_result["count"] == 1
    assert read_result["entries"][0]["value"] == "assess"


@pytest.mark.asyncio
async def test_read_all_state(consultation_cleanup):
    """Reading without a key returns all entries."""
    match_result = await match_concepts(FLOW_CASE["description"], max_results=5)
    cid = consultation_cleanup(match_result["consultation_id"])

    await write_state(cid, "key_a", 1)
    await write_state(cid, "key_b", {"nested": True})

    read_result = await read_state(cid)
    assert read_result["count"] == 2


@pytest.mark.asyncio
async def test_read_nonexistent_key(consultation_cleanup):
    """Reading a key that doesn't exist returns empty."""
    match_result = await match_concepts(FLOW_CASE["description"], max_results=5)
    cid = consultation_cleanup(match_result["consultation_id"])

    read_result = await read_state(cid, "nonexistent")
    assert read_result["count"] == 0
    assert read_result["entries"] == []


@pytest.mark.asyncio
async def test_write_state_invalid_consultation():
    """Writing to a nonexistent consultation returns error."""
    result = await write_state("nonexistent_id", "key", "value")
    assert "error" in result


@pytest.mark.asyncio
async def test_write_state_missing_key(consultation_cleanup):
    """Writing with empty key returns error."""
    match_result = await match_concepts(FLOW_CASE["description"], max_results=5)
    cid = consultation_cleanup(match_result["consultation_id"])

    result = await write_state(cid, "", "value")
    assert "error" in result
