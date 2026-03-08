"""Test generate_failure_scenarios with synthetic pattern assessments.

Creates a consultation, injects pattern_assessment steps from test cases,
and validates the failure scenario output structure and determinism.
"""

import pytest

from tests.cases import CASES, CASES_BY_ID

from iconsult_mcp.tools.match_concepts import match_concepts
from iconsult_mcp.tools.failure_scenarios import generate_failure_scenarios
from iconsult_mcp.db import log_consultation_step


# Use cases that have at least one missing pattern (for scenario generation)
SCENARIO_CASES = [
    c for c in CASES
    if any(pa.get("status") == "missing" for pa in c.get("pattern_assessments", []))
]


@pytest.fixture(params=SCENARIO_CASES, ids=[c["id"] for c in SCENARIO_CASES])
def case(request):
    return request.param


@pytest.mark.asyncio
async def test_failure_scenarios_produces_valid_output(case, consultation_cleanup):
    """Failure scenarios returns all expected sections."""
    result = await match_concepts(case["description"], max_results=5)
    cid = consultation_cleanup(result["consultation_id"])

    # Inject pattern assessments
    for pa in case["pattern_assessments"]:
        log_consultation_step(cid, "pattern_assessment", pa)

    scenarios = await generate_failure_scenarios(cid)

    assert "error" not in scenarios, scenarios.get("error")
    assert scenarios["consultation_id"] == cid

    # Structure checks
    assert "scenarios" in scenarios
    assert "failure_chain" in scenarios
    assert "summary" in scenarios

    # Each scenario must have required fields
    for s in scenarios["scenarios"]:
        assert "scenario_id" in s
        assert "title" in s
        assert "trigger" in s
        assert "missing_pattern" in s
        assert "severity" in s
        assert s["severity"] in ("CRITICAL", "WARNING", "INFO")
        assert "cascade_steps" in s
        assert len(s["cascade_steps"]) > 0
        assert "book_reference" in s
        assert "mode" in s
        assert s["mode"] in ("code_grounded", "book_grounded")
        assert "recovery" in s

    # Failure chain must have 5 steps
    chain = scenarios["failure_chain"]
    assert len(chain["steps"]) == 5
    assert "chain_coverage" in chain
    assert "first_gap" in chain


@pytest.mark.asyncio
async def test_failure_scenarios_determinism(consultation_cleanup):
    """Same assessments produce identical scenarios."""
    case = SCENARIO_CASES[0]

    results = []
    for _ in range(2):
        result = await match_concepts(case["description"], max_results=5)
        cid = consultation_cleanup(result["consultation_id"])

        for pa in case["pattern_assessments"]:
            log_consultation_step(cid, "pattern_assessment", pa)

        scenarios = await generate_failure_scenarios(cid)
        results.append(scenarios)

    # Same number of scenarios
    assert len(results[0]["scenarios"]) == len(results[1]["scenarios"])

    # Same scenario titles in same order
    titles_0 = [s["title"] for s in results[0]["scenarios"]]
    titles_1 = [s["title"] for s in results[1]["scenarios"]]
    assert titles_0 == titles_1

    # Same failure chain coverage
    assert results[0]["failure_chain"]["chain_coverage"] == results[1]["failure_chain"]["chain_coverage"]


@pytest.mark.asyncio
async def test_failure_scenarios_empty_when_all_implemented(consultation_cleanup):
    """No scenarios when all patterns are implemented."""
    result = await match_concepts("fully implemented system", max_results=5)
    cid = consultation_cleanup(result["consultation_id"])

    # Inject all-implemented assessments
    log_consultation_step(cid, "pattern_assessment", {
        "pattern_id": "single_agent_baseline_pattern",
        "pattern_name": "Single Agent Baseline",
        "status": "implemented",
        "evidence": "complete implementation",
        "maturity_level": 1,
    })
    log_consultation_step(cid, "pattern_assessment", {
        "pattern_id": "watchdog_timeout_pattern",
        "pattern_name": "Watchdog Timeout",
        "status": "implemented",
        "evidence": "timeouts on all API calls",
        "maturity_level": 1,
    })

    scenarios = await generate_failure_scenarios(cid)

    assert "error" not in scenarios
    assert scenarios["scenario_count"] == 0
    assert len(scenarios["scenarios"]) == 0


@pytest.mark.asyncio
async def test_failure_scenarios_with_code_evidence(consultation_cleanup):
    """Scenarios include code references when failure_context has code_refs."""
    case = CASES_BY_ID["financial_research"]

    result = await match_concepts(case["description"], max_results=5)
    cid = consultation_cleanup(result["consultation_id"])

    for pa in case["pattern_assessments"]:
        log_consultation_step(cid, "pattern_assessment", pa)

    scenarios = await generate_failure_scenarios(cid)
    assert "error" not in scenarios

    # Find the watchdog_timeout scenario (which has code_refs in failure_context)
    code_grounded = [
        s for s in scenarios["scenarios"]
        if s["mode"] == "code_grounded"
    ]
    assert len(code_grounded) > 0, (
        "Expected at least one code_grounded scenario from financial_research case"
    )

    # Check that cascade steps have code_ref attached
    for s in code_grounded:
        has_code_ref = any(
            step.get("code_ref") is not None
            for step in s["cascade_steps"]
        )
        assert has_code_ref, (
            f"Code-grounded scenario '{s['title']}' should have at least one code_ref"
        )


@pytest.mark.asyncio
async def test_failure_chain_coverage(consultation_cleanup):
    """Failure chain maps correctly against assessments."""
    case = CASES_BY_ID["financial_research"]

    result = await match_concepts(case["description"], max_results=5)
    cid = consultation_cleanup(result["consultation_id"])

    for pa in case["pattern_assessments"]:
        log_consultation_step(cid, "pattern_assessment", pa)

    scenarios = await generate_failure_scenarios(cid)
    chain = scenarios["failure_chain"]

    # Check that assessed patterns are correctly mapped
    for step in chain["steps"]:
        if step["pattern_id"] == "watchdog_timeout_pattern":
            assert step["status"] == "missing"
            assert step["gap"] is True
        if step["pattern_id"] == "agent_calls_human_pattern":
            assert step["status"] == "missing"
            assert step["gap"] is True


@pytest.mark.asyncio
async def test_failure_scenarios_severity_ordering(consultation_cleanup):
    """Scenarios are sorted by severity (CRITICAL first)."""
    case = CASES_BY_ID["financial_research"]

    result = await match_concepts(case["description"], max_results=5)
    cid = consultation_cleanup(result["consultation_id"])

    for pa in case["pattern_assessments"]:
        log_consultation_step(cid, "pattern_assessment", pa)

    scenarios = await generate_failure_scenarios(cid, max_scenarios=10)

    if len(scenarios["scenarios"]) >= 2:
        severity_order = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
        severities = [
            severity_order[s["severity"]]
            for s in scenarios["scenarios"]
        ]
        assert severities == sorted(severities), (
            "Scenarios should be sorted by severity (CRITICAL first)"
        )


@pytest.mark.asyncio
async def test_failure_scenarios_max_scenarios_cap(consultation_cleanup):
    """max_scenarios parameter limits output."""
    case = CASES_BY_ID["financial_research"]

    result = await match_concepts(case["description"], max_results=5)
    cid = consultation_cleanup(result["consultation_id"])

    for pa in case["pattern_assessments"]:
        log_consultation_step(cid, "pattern_assessment", pa)

    scenarios = await generate_failure_scenarios(cid, max_scenarios=2)
    assert len(scenarios["scenarios"]) <= 2


@pytest.mark.asyncio
async def test_failure_scenarios_no_assessments_errors(consultation_cleanup):
    """Error when no assessments exist."""
    result = await match_concepts("empty project", max_results=5)
    cid = consultation_cleanup(result["consultation_id"])

    scenarios = await generate_failure_scenarios(cid)
    assert "error" in scenarios
