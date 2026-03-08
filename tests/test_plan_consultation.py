"""Tests for adaptive consultation planning."""

import pytest

from iconsult_mcp.tools.match_concepts import match_concepts
from iconsult_mcp.tools.plan_consultation import (
    plan_consultation,
    _assess_complexity,
    _generate_plan,
)
from iconsult_mcp.db import get_consultation

from tests.cases import CASES_BY_ID

FLOW_CASE = CASES_BY_ID["financial_research"]


@pytest.mark.asyncio
async def test_plan_simple(consultation_cleanup):
    """A simple description produces a simple plan with fewer steps."""
    match_result = await match_concepts("A basic chatbot agent", max_results=5)
    cid = consultation_cleanup(match_result["consultation_id"])

    result = await plan_consultation(cid)
    assert "error" not in result
    assert result["complexity"]["level"] in ("simple", "moderate")
    assert result["step_count"] >= 3


@pytest.mark.asyncio
async def test_plan_complex(consultation_cleanup):
    """A complex description produces a complex plan with more steps."""
    match_result = await match_concepts(FLOW_CASE["description"], max_results=15)
    cid = consultation_cleanup(match_result["consultation_id"])

    result = await plan_consultation(cid)
    assert "error" not in result
    assert result["step_count"] >= 6
    # Complex plans should have a traverse step
    actions = [s["action"] for s in result["plan"]]
    assert "traverse" in actions
    assert "synthesize" in actions


@pytest.mark.asyncio
async def test_plan_logs_step(consultation_cleanup):
    """Planning logs a plan_created step."""
    match_result = await match_concepts(FLOW_CASE["description"], max_results=5)
    cid = consultation_cleanup(match_result["consultation_id"])

    await plan_consultation(cid)

    record = get_consultation(cid)
    plan_steps = [s for s in record["steps"] if s["type"] == "plan_created"]
    assert len(plan_steps) == 1
    assert "complexity" in plan_steps[0]


@pytest.mark.asyncio
async def test_plan_invalid_consultation():
    """Planning a nonexistent consultation returns error."""
    result = await plan_consultation("nonexistent_id")
    assert "error" in result


def test_assess_complexity_simple():
    """Low concept count + no keywords = simple."""
    result = _assess_complexity(3, "A simple chatbot", 1.0)
    assert result["level"] == "simple"
    assert result["score"] < 30


def test_assess_complexity_complex():
    """High concept count + many keywords + high density = complex."""
    result = _assess_complexity(
        15,
        "A distributed multi-agent orchestration system with consensus, "
        "fault-tolerant event-driven architecture and human-in-the-loop guardrails",
        5.0,
    )
    assert result["level"] == "complex"
    assert result["score"] >= 65
