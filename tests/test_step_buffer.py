"""Test write-behind buffer for consultation step logging."""

import pytest

from iconsult_mcp.tools.match_concepts import match_concepts
from iconsult_mcp.db import (
    get_connection,
    log_consultation_step,
    flush_consultation_steps,
    flush_all_steps,
    get_consultation,
    get_pattern_assessments,
    get_pending_steps,
    discard_pending_steps,
)


@pytest.mark.asyncio
async def test_buffer_append_no_db_write(consultation_cleanup):
    """log_consultation_step buffers in memory; DB steps unchanged until flush."""
    result = await match_concepts("Simple chatbot", max_results=3)
    cid = consultation_cleanup(result["consultation_id"])

    log_consultation_step(cid, "subgraph_traversal", {"concept_id": "c1"})
    log_consultation_step(cid, "subgraph_traversal", {"concept_id": "c2"})

    # Buffer should have 2 entries
    assert len(get_pending_steps(cid)) == 2

    # DB should still have empty steps (no flush yet)
    conn = get_connection()
    import json
    row = conn.execute("SELECT steps FROM consultations WHERE id = ?", [cid]).fetchone()
    db_steps = json.loads(row[0]) if row[0] else []
    assert len(db_steps) == 0


@pytest.mark.asyncio
async def test_flush_writes_all_steps(consultation_cleanup):
    """flush_consultation_steps batch-writes all buffered steps in one cycle."""
    result = await match_concepts("Simple chatbot", max_results=3)
    cid = consultation_cleanup(result["consultation_id"])

    log_consultation_step(cid, "subgraph_traversal", {"concept_id": "c1"})
    log_consultation_step(cid, "passage_retrieval", {"question": "q1"})
    log_consultation_step(cid, "state_write", {"key": "k1"})

    count = flush_consultation_steps(cid)
    assert count == 3

    # Buffer should be empty
    assert len(get_pending_steps(cid)) == 0

    # DB should have all 3 steps
    conn = get_connection()
    import json
    row = conn.execute("SELECT steps FROM consultations WHERE id = ?", [cid]).fetchone()
    db_steps = json.loads(row[0]) if row[0] else []
    assert len(db_steps) == 3
    assert db_steps[0]["type"] == "subgraph_traversal"
    assert db_steps[1]["type"] == "passage_retrieval"
    assert db_steps[2]["type"] == "state_write"


@pytest.mark.asyncio
async def test_auto_flush_on_get_consultation(consultation_cleanup):
    """get_consultation() auto-flushes; returned record includes buffered steps."""
    result = await match_concepts("Simple chatbot", max_results=3)
    cid = consultation_cleanup(result["consultation_id"])

    log_consultation_step(cid, "subgraph_traversal", {"concept_id": "c1"})
    log_consultation_step(cid, "subgraph_traversal", {"concept_id": "c2"})

    # get_consultation should auto-flush and return steps
    record = get_consultation(cid)
    assert len(record["steps"]) == 2

    # Buffer should be empty after auto-flush
    assert len(get_pending_steps(cid)) == 0


@pytest.mark.asyncio
async def test_auto_flush_on_get_pattern_assessments(consultation_cleanup):
    """get_pattern_assessments() auto-flushes; returns buffered pattern_assessment steps."""
    result = await match_concepts("Simple chatbot", max_results=3)
    cid = consultation_cleanup(result["consultation_id"])

    log_consultation_step(cid, "pattern_assessment", {
        "pattern_id": "retry", "pattern_name": "Retry", "status": "implemented",
        "maturity_level": 3,
    })
    log_consultation_step(cid, "subgraph_traversal", {"concept_id": "c1"})

    assessments = get_pattern_assessments(cid)
    assert len(assessments) == 1
    assert assessments[0]["pattern_id"] == "retry"

    # Buffer should be empty
    assert len(get_pending_steps(cid)) == 0


@pytest.mark.asyncio
async def test_empty_flush_is_noop(consultation_cleanup):
    """Flushing with no buffered steps returns 0, no DB error."""
    result = await match_concepts("Simple chatbot", max_results=3)
    cid = consultation_cleanup(result["consultation_id"])

    count = flush_consultation_steps(cid)
    assert count == 0

    # Consultation still valid
    record = get_consultation(cid)
    assert record is not None
    assert record["steps"] == []


@pytest.mark.asyncio
async def test_flush_nonexistent_consultation(consultation_cleanup):
    """Flushing for a deleted/nonexistent consultation discards buffer gracefully."""
    fake_cid = "nonexistent-buffer-test-id"

    log_consultation_step(fake_cid, "subgraph_traversal", {"concept_id": "c1"})
    assert len(get_pending_steps(fake_cid)) == 1

    # Should not raise; discards buffer since consultation doesn't exist
    count = flush_consultation_steps(fake_cid)
    assert count == 0
    assert len(get_pending_steps(fake_cid)) == 0


@pytest.mark.asyncio
async def test_flush_all_multiple_consultations(consultation_cleanup):
    """flush_all_steps() flushes buffers for 2+ consultations."""
    r1 = await match_concepts("Simple chatbot", max_results=3)
    cid1 = consultation_cleanup(r1["consultation_id"])
    r2 = await match_concepts("Multi-agent pipeline", max_results=3)
    cid2 = consultation_cleanup(r2["consultation_id"])

    log_consultation_step(cid1, "subgraph_traversal", {"concept_id": "c1"})
    log_consultation_step(cid2, "subgraph_traversal", {"concept_id": "c2"})
    log_consultation_step(cid2, "passage_retrieval", {"question": "q1"})

    total = flush_all_steps()
    assert total == 3

    rec1 = get_consultation(cid1)
    rec2 = get_consultation(cid2)
    assert len(rec1["steps"]) == 1
    assert len(rec2["steps"]) == 2


@pytest.mark.asyncio
async def test_blackboard_single_query_versioning(consultation_cleanup):
    """Assert 3 facts for same key -> versions 1, 2, 3 (validates subquery)."""
    from iconsult_mcp.tools.blackboard import assert_fact, query_facts

    result = await match_concepts("Simple chatbot", max_results=3)
    cid = consultation_cleanup(result["consultation_id"])

    for i in range(1, 4):
        res = await assert_fact(cid, "finding", "same_key", f"value_{i}", agent_id="agent_x")
        assert "error" not in res

    qr = await query_facts(cid, key="same_key")
    assert qr["fact_count"] == 3
    versions = sorted(f["version"] for f in qr["facts"])
    assert versions == [1, 2, 3]


@pytest.mark.asyncio
async def test_end_to_end_buffer_with_scoring(consultation_cleanup):
    """Buffer 5 pattern assessments -> score_architecture() sees all 5."""
    from iconsult_mcp.tools.score_architecture import score_architecture

    result = await match_concepts(
        "Multi-agent system with supervisor orchestrating worker agents", max_results=5,
    )
    cid = consultation_cleanup(result["consultation_id"])

    assessments = [
        {"pattern_id": "simple_retry", "pattern_name": "Simple Retry", "status": "implemented", "maturity_level": 1},
        {"pattern_id": "agent_calls_human", "pattern_name": "Agent Calls Human", "status": "implemented", "maturity_level": 1},
        {"pattern_id": "supervisor_architecture", "pattern_name": "Supervisor Architecture", "status": "partial", "maturity_level": 1},
        {"pattern_id": "watchdog_timeout", "pattern_name": "Watchdog Timeout", "status": "missing", "maturity_level": 1},
        {"pattern_id": "consensus_and_negotiation", "pattern_name": "Consensus", "status": "not_applicable", "maturity_level": 1},
    ]
    for pa in assessments:
        log_consultation_step(cid, "pattern_assessment", pa)

    # All 5 still in buffer
    assert len(get_pending_steps(cid)) == 5

    # score_architecture calls get_pattern_assessments which auto-flushes
    score = await score_architecture(cid)
    assert "error" not in score, score.get("error")

    # Buffer should be empty now
    assert len(get_pending_steps(cid)) == 0

    # Should have found all 5 rubric pattern assessments
    assert score["overall_summary"]["total_assessed"] == 5
