"""Test blackboard knowledge hub — assert/query facts, conflict detection, TTL, convergence."""

import pytest
import time

from iconsult_mcp.tools.match_concepts import match_concepts
from iconsult_mcp.tools.blackboard import assert_fact, query_facts


@pytest.mark.asyncio
async def test_assert_and_query_fact(consultation_cleanup):
    """Assert a fact and query it back."""
    result = await match_concepts("Simple chatbot", max_results=3)
    cid = consultation_cleanup(result["consultation_id"])

    # Assert
    res = await assert_fact(cid, "concept_finding", "router_pattern", {"found": True}, confidence=0.9, agent_id="agent_1")
    assert "error" not in res
    assert res["fact_id"] > 0
    assert res["confidence"] == 0.9

    # Query
    qr = await query_facts(cid, fact_type="concept_finding")
    assert qr["fact_count"] == 1
    assert qr["facts"][0]["key"] == "router_pattern"
    assert qr["facts"][0]["value"] == {"found": True}
    assert qr["facts"][0]["agent_id"] == "agent_1"


@pytest.mark.asyncio
async def test_append_only_versioning(consultation_cleanup):
    """Multiple assertions for same key create new versions, not overwrites."""
    result = await match_concepts("Simple chatbot", max_results=3)
    cid = consultation_cleanup(result["consultation_id"])

    await assert_fact(cid, "finding", "key1", "v1", agent_id="a1")
    await assert_fact(cid, "finding", "key1", "v2", agent_id="a1")

    qr = await query_facts(cid, key="key1")
    assert qr["fact_count"] == 2
    versions = [f["version"] for f in qr["facts"]]
    assert 1 in versions
    assert 2 in versions


@pytest.mark.asyncio
async def test_conflict_detection(consultation_cleanup):
    """Different agents asserting different values for the same key are detected as conflicts."""
    result = await match_concepts("Multi-agent system", max_results=3)
    cid = consultation_cleanup(result["consultation_id"])

    await assert_fact(cid, "pattern_status", "retry", "implemented", agent_id="agent_a")
    await assert_fact(cid, "pattern_status", "retry", "missing", agent_id="agent_b")

    qr = await query_facts(cid, key="retry", detect_conflicts=True)
    assert qr["has_conflicts"] is True
    assert len(qr["conflicts"]) == 2


@pytest.mark.asyncio
async def test_no_conflict_when_same_value(consultation_cleanup):
    """Same value from different agents is not a conflict."""
    result = await match_concepts("Simple chatbot", max_results=3)
    cid = consultation_cleanup(result["consultation_id"])

    await assert_fact(cid, "finding", "key1", "agreed", agent_id="a1")
    await assert_fact(cid, "finding", "key1", "agreed", agent_id="a2")

    qr = await query_facts(cid, key="key1", detect_conflicts=True)
    assert qr["has_conflicts"] is False


@pytest.mark.asyncio
async def test_convergence_status(consultation_cleanup):
    """Convergence check reports converged and conflicting keys."""
    result = await match_concepts("Multi-agent system", max_results=3)
    cid = consultation_cleanup(result["consultation_id"])

    # Converged key
    await assert_fact(cid, "finding", "converged_key", "same", agent_id="a1")
    await assert_fact(cid, "finding", "converged_key", "same", agent_id="a2")

    # Conflicting key
    await assert_fact(cid, "finding", "conflict_key", "yes", agent_id="a1")
    await assert_fact(cid, "finding", "conflict_key", "no", agent_id="a2")

    qr = await query_facts(cid, detect_conflicts=True)
    conv = qr["convergence"]
    assert conv["total_keys"] == 2
    assert conv["converged_keys"] == 1
    assert conv["conflicting_keys"] == 1
    assert conv["convergence_pct"] == 50


@pytest.mark.asyncio
async def test_ttl_expiry(consultation_cleanup):
    """Facts with TTL=1 second expire and are excluded from queries."""
    result = await match_concepts("Simple chatbot", max_results=3)
    cid = consultation_cleanup(result["consultation_id"])

    await assert_fact(cid, "temp", "ephemeral", "value", ttl_seconds=1)

    # Should be visible immediately
    qr = await query_facts(cid, key="ephemeral")
    assert qr["fact_count"] == 1

    # Wait for expiry
    time.sleep(2)

    # Should be gone
    qr = await query_facts(cid, key="ephemeral")
    assert qr["fact_count"] == 0

    # But visible with include_expired (query via db directly)
    from iconsult_mcp.db import query_blackboard_facts
    facts = query_blackboard_facts(cid, key="ephemeral", include_expired=True)
    assert len(facts) == 1


@pytest.mark.asyncio
async def test_min_confidence_filter(consultation_cleanup):
    """Facts below min_confidence threshold are excluded."""
    result = await match_concepts("Simple chatbot", max_results=3)
    cid = consultation_cleanup(result["consultation_id"])

    await assert_fact(cid, "finding", "low", "val", confidence=0.3)
    await assert_fact(cid, "finding", "high", "val", confidence=0.9)

    qr = await query_facts(cid, min_confidence=0.5)
    assert qr["fact_count"] == 1
    assert qr["facts"][0]["key"] == "high"


@pytest.mark.asyncio
async def test_validation_errors(consultation_cleanup):
    """Assert and query with invalid inputs return errors."""
    res = await assert_fact("", "type", "key", "val")
    assert "error" in res

    res = await assert_fact("nonexistent-id", "type", "key", "val")
    assert "error" in res

    res = await query_facts("")
    assert "error" in res


@pytest.mark.asyncio
async def test_shared_state_bridge(consultation_cleanup):
    """write_state with agent_id also creates a blackboard fact."""
    from iconsult_mcp.tools.shared_state import write_state

    result = await match_concepts("Simple chatbot", max_results=3)
    cid = consultation_cleanup(result["consultation_id"])

    await write_state(cid, "discovered_concepts", ["c1", "c2"], agent_id="explorer_1")

    # Should appear in blackboard
    qr = await query_facts(cid, fact_type="shared_state", key="discovered_concepts")
    assert qr["fact_count"] == 1
    assert qr["facts"][0]["agent_id"] == "explorer_1"
    assert qr["facts"][0]["value"] == ["c1", "c2"]
