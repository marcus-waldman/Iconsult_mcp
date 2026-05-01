"""B2 — critique_consultation no longer reports false positives for
match_concepts and failure scenarios.

Two real bugs surfaced during the Phase 6 6b run:

  - critique flagged "Missing workflow step: 'match_concepts'" on every
    consultation, because match_concepts intentionally creates the row but
    does NOT write a step. The check looked for a step type that no tool
    ever logs.

  - critique flagged "Missing/partial patterns found but no failure
    scenarios generated" even when generate_failure_scenarios HAD been
    called, because that tool also never wrote a step. The check looked
    for a step type that no tool ever logs.

Fix:
  - Drop "match_concepts" from WORKFLOW_STEPS (existence of the
    consultation row is the proof it ran).
  - Have generate_failure_scenarios log a "failure_scenarios_generated"
    step on completion, symmetric with plan_created / quality_rated /
    implementation_plan_generated. Rename the critique lookup to match.

These tests pin both bugs.
"""

from __future__ import annotations

import pytest

from iconsult_mcp.db import (
    create_consultation,
    flush_consultation_steps,
    get_consultation,
    log_consultation_step,
)
from iconsult_mcp.tools.critique_consultation import (
    WORKFLOW_STEPS,
    critique_consultation,
)
from iconsult_mcp.tools.failure_scenarios import generate_failure_scenarios
from iconsult_mcp.tools.log_pattern_assessment import log_pattern_assessment


def _make_consultation(cid: str, matched: list[str] | None = None) -> str:
    create_consultation(
        consultation_id=cid,
        fingerprint=f"fp-{cid}",
        description="critique test",
        concept_ids=matched or [],
        scores=[0.9] * len(matched or []),
    )
    return cid


# --- workflow check no longer demands match_concepts step ------------------


def test_workflow_steps_does_not_include_match_concepts():
    """Pin the contract: match_concepts is NOT a workflow step type because
    no tool logs that step (it creates the consultation row, period)."""
    assert "match_concepts" not in WORKFLOW_STEPS


@pytest.mark.asyncio
async def test_critique_does_not_flag_missing_match_concepts(consultation_cleanup):
    """A consultation with the three actually-logged workflow steps
    (get_subgraph + pattern_assessment + ask_book) must NOT produce a
    'Missing workflow step: match_concepts' error."""
    cid = consultation_cleanup("critique_no_mc_001")
    _make_consultation(cid, matched=["c1", "c2"])

    log_consultation_step(cid, "get_subgraph", {
        "seed_concept_ids": ["c1"],
        "discovered_concept_ids": ["c1", "c2"],
        "relationship_types_seen": ["uses", "requires"],
    })
    await log_pattern_assessment(
        consultation_id=cid,
        pattern_id="supervisor_architecture",
        pattern_name="Supervisor Architecture",
        status="implemented",
    )
    log_consultation_step(cid, "ask_book", {
        "question": "How does supervision work?",
        "chapters_seen": [12],
        "sections_returned": ["s1"],
    })

    flush_consultation_steps(cid)
    result = await critique_consultation(cid)

    workflow_msgs = [
        i["message"] for i in result["issues"]
        if i.get("category") == "workflow"
    ]
    assert not any("match_concepts" in m for m in workflow_msgs), (
        f"Did not expect match_concepts to be flagged. Got: {workflow_msgs}"
    )


# --- failure_scenarios_generated step is the new detection signal ---------


@pytest.mark.asyncio
async def test_generate_failure_scenarios_logs_a_step(consultation_cleanup):
    """generate_failure_scenarios must persist a step so downstream tools
    can detect the workflow phase ran. This is the symmetric fix to bug #2."""
    cid = consultation_cleanup("critique_fs_logs_001")
    _make_consultation(cid, matched=["c1"])

    # Need at least one missing/partial assessment so scenarios are produced
    await log_pattern_assessment(
        consultation_id=cid,
        pattern_id="watchdog_timeout",
        pattern_name="Watchdog Timeout",
        status="missing",
    )

    result = await generate_failure_scenarios(cid)
    assert "error" not in result

    flush_consultation_steps(cid)
    record = get_consultation(cid)
    fs_steps = [s for s in record["steps"] if s.get("type") == "failure_scenarios_generated"]
    assert len(fs_steps) == 1
    assert fs_steps[0]["scenario_count"] == result["scenario_count"]


@pytest.mark.asyncio
async def test_critique_does_not_flag_failure_scenarios_when_called(
    consultation_cleanup,
):
    """When generate_failure_scenarios HAS been called, critique must not
    warn 'no failure scenarios generated' even with missing patterns."""
    cid = consultation_cleanup("critique_fs_called_001")
    _make_consultation(cid, matched=["c1", "c2"])

    log_consultation_step(cid, "get_subgraph", {
        "seed_concept_ids": ["c1"],
        "discovered_concept_ids": ["c1", "c2"],
        "relationship_types_seen": ["uses", "requires"],
    })
    await log_pattern_assessment(
        consultation_id=cid,
        pattern_id="watchdog_timeout",
        pattern_name="Watchdog Timeout",
        status="missing",  # triggers the failure_scenarios detection branch
    )
    log_consultation_step(cid, "ask_book", {
        "question": "How do timeouts work?",
        "chapters_seen": [7],
        "sections_returned": ["s7"],
    })

    fs_result = await generate_failure_scenarios(cid)
    assert "error" not in fs_result

    flush_consultation_steps(cid)
    result = await critique_consultation(cid)

    fs_msgs = [
        i["message"] for i in result["issues"]
        if i.get("category") == "failure_scenarios"
    ]
    assert not fs_msgs, (
        f"Expected no failure_scenarios warnings; got: {fs_msgs}"
    )


@pytest.mark.asyncio
async def test_critique_still_flags_missing_failure_scenarios_when_not_called(
    consultation_cleanup,
):
    """Negative control: when missing/partial patterns exist AND
    generate_failure_scenarios has NOT been called, critique must still warn.
    The fix should not silence legitimate gaps."""
    cid = consultation_cleanup("critique_fs_missing_001")
    _make_consultation(cid, matched=["c1"])

    await log_pattern_assessment(
        consultation_id=cid,
        pattern_id="watchdog_timeout",
        pattern_name="Watchdog Timeout",
        status="missing",
    )

    flush_consultation_steps(cid)
    result = await critique_consultation(cid)

    fs_msgs = [
        i["message"] for i in result["issues"]
        if i.get("category") == "failure_scenarios"
    ]
    assert fs_msgs, "Expected critique to warn when failure scenarios were not generated"
    assert any("failure scenarios" in m.lower() for m in fs_msgs)
