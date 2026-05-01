"""Phase 5b — failure_scenarios attaches source_book_id to every scenario.

Locked design (briefing 5b-Q1, option 1): every scenario carries
`source_book_id`. When the matching pattern_assessment supplied one,
that wins. Otherwise default to `arsanjani_2026` — every entry in
PATTERN_FAILURE_TEMPLATES is sourced from Ch. 7-12 of arsanjani, and the
rubric itself IS arsanjani Ch. 12, so a book-grounded scenario is
arsanjani-sourced by construction.

Invariants:
- Every generated scenario carries a non-empty `source_book_id`.
- A user-logged provenance value (e.g., "gulli_2025") wins over the
  default for that scenario.
- The default for a missing-pattern scenario with no user-supplied
  provenance is `arsanjani_2026` (the rubric oracle).
- Aliased pattern_ids (e.g. `gulli_2025__supervisor_architecture`)
  still attach provenance on the scenario keyed under the canonical
  rubric pattern.
"""

from __future__ import annotations

import pytest

from iconsult_mcp.db import (
    create_consultation,
    flush_consultation_steps,
)
from iconsult_mcp.tools.log_pattern_assessment import log_pattern_assessment
from iconsult_mcp.tools.failure_scenarios import generate_failure_scenarios


def _make_consultation(cid: str, project_id: str | None = None) -> str:
    create_consultation(
        consultation_id=cid,
        fingerprint=f"fp-{cid}",
        description="phase5b provenance test",
        concept_ids=[],
        scores=[],
        project_id=project_id,
    )
    return cid


# --- defaulting -------------------------------------------------------------


@pytest.mark.asyncio
async def test_book_grounded_defaults_to_arsanjani(consultation_cleanup):
    """A 'missing' assessment without source_book_id → scenarios for that
    pattern default to arsanjani_2026 (the rubric oracle)."""
    cid = consultation_cleanup("phase5b_default_001")
    _make_consultation(cid)

    # supervisor_architecture has a PATTERN_FAILURE_TEMPLATE entry
    await log_pattern_assessment(
        consultation_id=cid,
        pattern_id="supervisor_architecture",
        pattern_name="Supervisor Architecture",
        status="missing",
    )
    flush_consultation_steps(cid)

    result = await generate_failure_scenarios(cid, max_scenarios=10)
    assert "error" not in result
    assert result["scenarios"], "expected at least one scenario for the missing pattern"

    matched = [
        s for s in result["scenarios"]
        if s["missing_pattern"]["id"] == "supervisor_architecture"
    ]
    assert len(matched) == 1
    assert matched[0]["source_book_id"] == "arsanjani_2026"


@pytest.mark.asyncio
async def test_every_scenario_has_source_book_id(consultation_cleanup):
    """No scenario should ever miss source_book_id — even when the
    assessment is bare (no provenance, no failure_context)."""
    cid = consultation_cleanup("phase5b_universal_001")
    _make_consultation(cid)

    # Two missing patterns, no provenance on either
    for pid, pname in [
        ("supervisor_architecture", "Supervisor Architecture"),
        ("agent_calls_human", "Agent Calls Human"),
    ]:
        await log_pattern_assessment(
            consultation_id=cid,
            pattern_id=pid,
            pattern_name=pname,
            status="missing",
        )
    flush_consultation_steps(cid)

    result = await generate_failure_scenarios(cid, max_scenarios=10)
    assert "error" not in result
    assert result["scenarios"]
    for s in result["scenarios"]:
        assert s.get("source_book_id"), (
            f"scenario {s.get('scenario_id')} for "
            f"{s['missing_pattern']['name']} missing source_book_id"
        )


# --- user-supplied provenance wins ----------------------------------------


@pytest.mark.asyncio
async def test_user_supplied_provenance_wins(consultation_cleanup):
    """A 'missing' assessment with source_book_id='gulli_2025' →
    the scenario for that pattern carries gulli_2025, not the default."""
    cid = consultation_cleanup("phase5b_user_wins_001")
    _make_consultation(cid, project_id="proj_phase5b_user")

    await log_pattern_assessment(
        consultation_id=cid,
        pattern_id="supervisor_architecture",
        pattern_name="Supervisor Architecture",
        status="missing",
        source_book_id="gulli_2025",
        canonical_concept_id="proj_phase5b_user__supervisor",
    )
    flush_consultation_steps(cid)

    result = await generate_failure_scenarios(cid, max_scenarios=10)
    assert "error" not in result
    matched = [
        s for s in result["scenarios"]
        if s["missing_pattern"]["id"] == "supervisor_architecture"
    ]
    assert len(matched) == 1
    assert matched[0]["source_book_id"] == "gulli_2025"


@pytest.mark.asyncio
async def test_mixed_provenance_per_scenario(consultation_cleanup):
    """Two missing patterns with different provenance → each scenario
    carries its own source_book_id; defaults intermix with user-supplied."""
    cid = consultation_cleanup("phase5b_mixed_001")
    _make_consultation(cid, project_id="proj_phase5b_mixed")

    await log_pattern_assessment(
        consultation_id=cid,
        pattern_id="supervisor_architecture",
        pattern_name="Supervisor Architecture",
        status="missing",
        source_book_id="gulli_2025",
    )
    await log_pattern_assessment(
        consultation_id=cid,
        pattern_id="agent_calls_human",
        pattern_name="Agent Calls Human",
        status="missing",
        # no source_book_id → defaults to arsanjani_2026
    )
    flush_consultation_steps(cid)

    result = await generate_failure_scenarios(cid, max_scenarios=10)
    assert "error" not in result
    by_pid = {
        s["missing_pattern"]["id"]: s["source_book_id"]
        for s in result["scenarios"]
    }
    assert by_pid.get("supervisor_architecture") == "gulli_2025"
    assert by_pid.get("agent_calls_human") == "arsanjani_2026"


# --- aliased pattern_id ----------------------------------------------------


@pytest.mark.asyncio
async def test_aliased_pattern_id_carries_provenance(consultation_cleanup):
    """A book-prefixed pattern_id `gulli_2025__supervisor_architecture` is
    normalised to the rubric canonical, but the scenario still carries
    the user-supplied source_book_id verbatim."""
    cid = consultation_cleanup("phase5b_alias_001")
    _make_consultation(cid)

    await log_pattern_assessment(
        consultation_id=cid,
        pattern_id="gulli_2025__supervisor_architecture",
        pattern_name="Supervisor Architecture",
        status="missing",
        source_book_id="gulli_2025",
    )
    flush_consultation_steps(cid)

    result = await generate_failure_scenarios(cid, max_scenarios=10)
    assert "error" not in result
    matched = [
        s for s in result["scenarios"]
        if s["missing_pattern"]["id"] == "supervisor_architecture"
    ]
    assert len(matched) == 1
    assert matched[0]["source_book_id"] == "gulli_2025"
