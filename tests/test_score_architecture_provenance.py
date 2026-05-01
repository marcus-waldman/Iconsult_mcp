"""Phase 5a — score_architecture surfaces provenance on per-pattern entries
and rolls up `by_source_book` on `overall_summary`.

Invariants:
- A pattern_assessment with `source_book_id` / `canonical_concept_id` shows
  those fields on the matching `categories[k]["levels"][lv]["patterns"]`
  entry. Without provenance, neither key appears (legacy shape preserved).
- `overall_summary["by_source_book"]` is emitted only when at least one
  assessment carries `source_book_id`. Single-book / legacy consultations
  keep their existing summary shape byte-identical.
- The rollup keys on canonical pattern_id, so logging via an alias
  (e.g. book-prefixed `gulli_2025__supervisor_architecture`) still rolls
  up under one count for the rubric pattern.
"""

from __future__ import annotations

import pytest

from iconsult_mcp.db import (
    create_consultation,
    flush_consultation_steps,
)
from iconsult_mcp.tools.log_pattern_assessment import log_pattern_assessment
from iconsult_mcp.tools.score_architecture import score_architecture


def _make_consultation(cid: str, project_id: str | None = None) -> str:
    create_consultation(
        consultation_id=cid,
        fingerprint=f"fp-{cid}",
        description="phase5a provenance test",
        concept_ids=[],
        scores=[],
        project_id=project_id,
    )
    return cid


# --- backwards compatibility -----------------------------------------------


@pytest.mark.asyncio
async def test_score_no_provenance_unchanged_shape(consultation_cleanup):
    """Legacy consultation (no source_book_id on any assessment) →
    no `by_source_book` on overall_summary, no `source_book_id` /
    `canonical_concept_id` on any pattern detail."""
    cid = consultation_cleanup("phase5a_legacy_001")
    _make_consultation(cid)

    await log_pattern_assessment(
        consultation_id=cid,
        pattern_id="supervisor_architecture",
        pattern_name="Supervisor Architecture",
        status="implemented",
    )
    flush_consultation_steps(cid)

    score = await score_architecture(cid)
    assert "error" not in score
    assert "by_source_book" not in score["overall_summary"]

    # Walk every per-pattern entry — the only assessed one has neither
    # provenance key, all others (unassessed) also lack them.
    for cat in score["categories"].values():
        for lv in cat["levels"].values():
            for p in lv.get("patterns", []):
                assert "source_book_id" not in p
                assert "canonical_concept_id" not in p


# --- per-pattern attribution -----------------------------------------------


@pytest.mark.asyncio
async def test_score_surfaces_provenance_on_pattern_detail(consultation_cleanup):
    """An assessment with provenance → the matching pattern entry inside
    `categories[k]["levels"][lv]["patterns"]` carries source_book_id and
    canonical_concept_id verbatim."""
    cid = consultation_cleanup("phase5a_perpattern_001")
    _make_consultation(cid, project_id="proj_phase5a_perpattern")

    await log_pattern_assessment(
        consultation_id=cid,
        pattern_id="supervisor_architecture",
        pattern_name="Supervisor Architecture",
        status="implemented",
        source_book_id="gulli_2025",
        canonical_concept_id="proj_phase5a_perpattern__supervisor",
    )
    flush_consultation_steps(cid)

    score = await score_architecture(cid)
    assert "error" not in score

    matched = None
    for cat in score["categories"].values():
        for lv in cat["levels"].values():
            for p in lv.get("patterns", []):
                if p["pattern_id"] == "supervisor_architecture":
                    matched = p
                    break
    assert matched is not None, "supervisor_architecture not found in any category level"
    assert matched["source_book_id"] == "gulli_2025"
    assert matched["canonical_concept_id"] == "proj_phase5a_perpattern__supervisor"
    assert matched["met"] is True

    # Sibling unassessed patterns in the same category must NOT have provenance
    # keys — provenance is per-assessment, not category-wide.
    for cat in score["categories"].values():
        for lv in cat["levels"].values():
            for p in lv.get("patterns", []):
                if p["pattern_id"] != "supervisor_architecture":
                    assert "source_book_id" not in p
                    assert "canonical_concept_id" not in p


# --- by_source_book rollup -------------------------------------------------


@pytest.mark.asyncio
async def test_by_source_book_rollup_multi_book(consultation_cleanup):
    """Two assessments with different source_book_ids → overall_summary
    gains `by_source_book` with one count per book. Counts canonical
    rubric patterns, so each pattern_id contributes at most once."""
    cid = consultation_cleanup("phase5a_rollup_multi_001")
    _make_consultation(cid, project_id="proj_phase5a_rollup")

    await log_pattern_assessment(
        consultation_id=cid,
        pattern_id="supervisor_architecture",
        pattern_name="Supervisor Architecture",
        status="implemented",
        source_book_id="arsanjani_2026",
    )
    await log_pattern_assessment(
        consultation_id=cid,
        pattern_id="agent_delegates_to_agent",
        pattern_name="Agent Delegates to Agent",
        status="implemented",
        source_book_id="gulli_2025",
    )
    flush_consultation_steps(cid)

    score = await score_architecture(cid)
    assert "error" not in score
    rollup = score["overall_summary"].get("by_source_book")
    assert rollup == {"arsanjani_2026": 1, "gulli_2025": 1}


@pytest.mark.asyncio
async def test_by_source_book_skipped_when_no_provenance(consultation_cleanup):
    """Mixed provenance: when ALL assessments lack source_book_id, the
    rollup key is absent. Confirms we don't synthesize an empty rollup
    or an `unknown` bucket."""
    cid = consultation_cleanup("phase5a_rollup_none_001")
    _make_consultation(cid)

    await log_pattern_assessment(
        consultation_id=cid,
        pattern_id="supervisor_architecture",
        pattern_name="Supervisor Architecture",
        status="implemented",
    )
    await log_pattern_assessment(
        consultation_id=cid,
        pattern_id="agent_delegates_to_agent",
        pattern_name="Agent Delegates to Agent",
        status="missing",
    )
    flush_consultation_steps(cid)

    score = await score_architecture(cid)
    assert "error" not in score
    assert "by_source_book" not in score["overall_summary"]


@pytest.mark.asyncio
async def test_by_source_book_aliased_pattern_counts_once(consultation_cleanup):
    """A book-prefixed pattern_id (`gulli_2025__supervisor_architecture`)
    aliases to the canonical rubric ID. The rollup should count one entry
    for the rubric pattern, not double-count the alias."""
    cid = consultation_cleanup("phase5a_rollup_alias_001")
    _make_consultation(cid)

    await log_pattern_assessment(
        consultation_id=cid,
        pattern_id="gulli_2025__supervisor_architecture",
        pattern_name="Supervisor Architecture",
        status="implemented",
        source_book_id="gulli_2025",
    )
    flush_consultation_steps(cid)

    score = await score_architecture(cid)
    assert "error" not in score
    assert score["overall_summary"]["by_source_book"] == {"gulli_2025": 1}
