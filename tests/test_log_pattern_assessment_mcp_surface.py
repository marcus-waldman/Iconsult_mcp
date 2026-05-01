"""B7 — log_pattern_assessment MCP surface exposes category + indicators.

The underlying tool function in `tools/log_pattern_assessment.py` accepts
``category`` (string) and ``indicators`` (list of dicts), both of which drive
status auto-computation and feed ``score_architecture``'s per-pattern
``missing_indicators`` gap analysis. Pre-fix, neither field was declared in
the MCP ``inputSchema`` nor forwarded by the dispatch lambda — MCP callers
silently lost both. The verify scripts and Phase 6 driver scripts bypass the
MCP transport via direct Python imports, so nothing in CI flagged this.

Three layers pinned here:

  - schema completeness: the MCP inputSchema declares ``category`` and
    ``indicators`` with the right types
  - dispatch wiring: the lambda forwards both args through to the tool fn,
    so indicators-driven auto-status flips ``missing`` → ``implemented``
    when all indicators are met
  - end-to-end through the harness: arrays arrive as JSON-encoded strings
    from Claude Code's MCP harness; ``coerce_typed_args`` decodes via the
    schema declaration, the dispatch lambda forwards the typed list, and
    ``score_architecture``'s ``missing_indicators`` populates correctly
"""

from __future__ import annotations

import asyncio
import json

import pytest

from iconsult_mcp.arg_coerce import coerce_typed_args
from iconsult_mcp.db import (
    create_consultation,
    flush_consultation_steps,
    get_consultation,
)
from iconsult_mcp.server import TOOL_DISPATCH, _get_tool_schemas
from iconsult_mcp.tools.score_architecture import (
    _get_pattern_assessments,
    score_architecture,
)


def _make_consultation(cid: str) -> str:
    create_consultation(
        consultation_id=cid,
        fingerprint=f"fp-{cid}",
        description="b7 mcp surface test",
        concept_ids=[],
        scores=[],
        project_id=None,
    )
    return cid


# --- schema completeness ----------------------------------------------------


def test_schema_declares_category_and_indicators():
    """The MCP inputSchema for log_pattern_assessment must declare both
    ``category`` (string) and ``indicators`` (array). Without these
    declarations they're invisible to MCP callers and ``coerce_typed_args``
    can't decode the harness's string-encoded ``indicators`` array either.
    """
    schemas = asyncio.run(_get_tool_schemas())
    schema = schemas["log_pattern_assessment"]
    props = schema["properties"]

    assert "category" in props, (
        "category missing from log_pattern_assessment inputSchema"
    )
    assert "indicators" in props, (
        "indicators missing from log_pattern_assessment inputSchema"
    )
    assert props["category"]["type"] == "string"
    assert props["indicators"]["type"] == "array"

    # Both fields stay optional — required list unchanged
    required = schema.get("required", [])
    assert "category" not in required
    assert "indicators" not in required


# --- dispatch lambda forwards both args ------------------------------------


@pytest.mark.asyncio
async def test_dispatch_lambda_forwards_category_and_indicators(
    consultation_cleanup,
):
    """The dispatch lambda for log_pattern_assessment must forward
    ``category`` and ``indicators`` from the args dict through to the tool
    fn. This is the wiring that lets MCP callers use indicators-driven
    status auto-computation.
    """
    cid = consultation_cleanup("b7_dispatch_pass_001")
    _make_consultation(cid)

    handler = TOOL_DISPATCH["log_pattern_assessment"]
    args = {
        "consultation_id": cid,
        "pattern_id": "supervisor_architecture",
        "pattern_name": "Supervisor Architecture",
        "status": "missing",  # should be overridden by all-met indicators
        "evidence": "B7 dispatch wiring test",
        "category": "coordination",
        "indicators": [
            {"text": "central orchestrator manages tasks", "met": True},
            {"text": "orchestrator receives results", "met": True},
            {"text": "workers return structured data", "met": True},
        ],
    }
    result = await handler(args)
    assert "error" not in result, f"unexpected error: {result}"

    # Auto-computation flips status to 'implemented' since all indicators met
    assert result["status"] == "implemented"
    assert result["category"] == "coordination"

    flush_consultation_steps(cid)
    record = get_consultation(cid)
    assessments = _get_pattern_assessments(record)
    a = assessments["supervisor_architecture"]
    assert a["status"] == "implemented"
    assert a.get("indicators") is not None
    assert len(a["indicators"]) == 3
    assert all(ind.get("met") for ind in a["indicators"])


# --- end-to-end via coerce_typed_args (Claude Code harness shape) ----------


@pytest.mark.asyncio
async def test_e2e_coerce_decodes_string_encoded_indicators_to_typed_list(
    consultation_cleanup,
):
    """End-to-end: Claude Code's MCP harness ships array params as
    JSON-encoded strings. With ``indicators`` declared as ``type: "array"``
    in the schema, ``coerce_typed_args`` decodes the string into a real
    list-of-dicts before dispatch. The tool fn's auto-status computation
    then runs over the decoded list, and ``score_architecture``'s
    ``gap_analysis`` picks up the ``missing_indicators`` correctly.
    """
    cid = consultation_cleanup("b7_e2e_coerce_001")
    _make_consultation(cid)

    schemas = await _get_tool_schemas()
    schema = schemas["log_pattern_assessment"]

    raw_args = {
        "consultation_id": cid,
        "pattern_id": "watchdog_timeout",
        "pattern_name": "Watchdog Timeout",
        "status": "implemented",  # should be overridden by all-not-met indicators
        "evidence": "B7 e2e coerce test",
        "category": "robustness",  # plain string, not coerced
        "indicators": json.dumps(
            [
                {"text": "agent function calls have explicit timeouts", "met": False},
                {"text": "timeout violations cancel running tasks", "met": False},
                {"text": "fallback mechanism on timeout", "met": False},
            ]
        ),
    }

    typed_args = coerce_typed_args(raw_args, schema)
    assert isinstance(typed_args["indicators"], list)
    assert len(typed_args["indicators"]) == 3
    assert isinstance(typed_args["indicators"][0], dict)
    assert typed_args["category"] == "robustness"

    handler = TOOL_DISPATCH["log_pattern_assessment"]
    result = await handler(typed_args)
    assert "error" not in result, f"unexpected error: {result}"

    # All indicators False → status auto-computes to 'missing'
    assert result["status"] == "missing"

    score = await score_architecture(consultation_id=cid)
    assert "error" not in score

    # gap_analysis surfaces missing_indicators per pattern
    gap = next(
        (g for g in score.get("gap_analysis", []) if g.get("pattern_id") == "watchdog_timeout"),
        None,
    )
    assert gap is not None, (
        "watchdog_timeout should appear in gap_analysis with missing indicators"
    )
    assert len(gap.get("missing_indicators", [])) == 3
    assert "explicit timeouts" in " ".join(gap["missing_indicators"])
