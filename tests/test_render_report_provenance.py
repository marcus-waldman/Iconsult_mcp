"""Phase 5c — render_report emits provenance badges for multi-book
consultations.

A consultation is "multi-book aware" when at least one logged
pattern_assessment carried `source_book_id` — score_architecture
surfaces that as `overall_summary["by_source_book"]`. That flag gates
whether `book-badge` HTML renders anywhere in the report.

Invariants:
- Legacy consultation (no provenance on any assessment) → no
  `book-badge` HTML anywhere in the rendered report. Critical for
  backwards compatibility.
- Multi-book consultation → `book-badge` HTML appears next to assessed
  pattern names in the scorecard AND next to scenario titles in the
  stress test section.
- Within a multi-book consultation, an unassessed pattern (sibling of
  an assessed one) does NOT get a badge — only entries with
  source_book_id do.
- The `.book-badge` CSS class is present in the rendered template
  whenever it could be needed (i.e., the template ships it).
"""

from __future__ import annotations

import os
import re
import tempfile

import pytest

from iconsult_mcp.db import (
    create_consultation,
    flush_consultation_steps,
)
from iconsult_mcp.tools.log_pattern_assessment import log_pattern_assessment
from iconsult_mcp.tools.render_report import render_report


_NARRATIVES = {
    "title": "Phase 5c Provenance Test",
    "executive_brief": "Test report for provenance badges.",
    "system_description": {
        "subtitle": "Test system",
        "architecture": "Test architecture",
        "tech_stack": "Test stack",
        "coordination": "Test coord",
        "security": "Test sec",
    },
    "agents": [],
    "diagram_current": "flowchart TD\n  A --> B",
    "diagram_target": "flowchart TD\n  A --> B --> C",
    "tooltips_current": {},
    "tooltips_target": {},
}


def _make_consultation(cid: str, project_id: str | None = None) -> str:
    create_consultation(
        consultation_id=cid,
        fingerprint=f"fp-{cid}",
        description="phase5c provenance test",
        concept_ids=[],
        scores=[],
        project_id=project_id,
    )
    return cid


async def _do_render(cid: str, tmpdir: str) -> dict:
    return await render_report(
        consultation_id=cid,
        output_dir=tmpdir,
        **_NARRATIVES,
    )


# --- legacy / single-book: no badges anywhere ------------------------------


@pytest.mark.asyncio
async def test_legacy_consultation_has_no_badges(consultation_cleanup):
    """A consultation where no assessment carries source_book_id → the
    rendered HTML must not contain any `book-badge` instance. Confirms
    backwards compatibility: legacy reports look exactly like before."""
    cid = consultation_cleanup("phase5c_legacy_001")
    _make_consultation(cid)

    await log_pattern_assessment(
        consultation_id=cid,
        pattern_id="supervisor_architecture",
        pattern_name="Supervisor Architecture",
        status="implemented",
    )
    await log_pattern_assessment(
        consultation_id=cid,
        pattern_id="agent_calls_human",
        pattern_name="Agent Calls Human",
        status="missing",
    )
    flush_consultation_steps(cid)

    with tempfile.TemporaryDirectory() as tmpdir:
        result = await _do_render(cid, tmpdir)
        with open(result["path"], "r", encoding="utf-8") as f:
            html = f.read()

    # The CSS class definition itself ships with the template — that's
    # OK, it's stylesheet-only. What we don't want is any *use* of the
    # class on an actual element.
    badge_uses = re.findall(r'<span class="book-badge"', html)
    assert badge_uses == [], (
        f"Legacy consultation should emit no book-badge spans, "
        f"found {len(badge_uses)}: {badge_uses}"
    )


# --- multi-book: badges in scorecard + stress test -------------------------


@pytest.mark.asyncio
async def test_multi_book_consultation_emits_badges(consultation_cleanup):
    """A consultation with source_book_id on at least one assessment →
    badges appear in the rendered HTML (both for the assessed pattern
    in the scorecard and for the failure scenarios it triggers)."""
    cid = consultation_cleanup("phase5c_multibook_001")
    _make_consultation(cid, project_id="proj_phase5c_multibook")

    # Two assessed patterns from different books — guarantees by_source_book
    # rollup → render_report turns badges on.
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
        status="missing",
        source_book_id="gulli_2025",
    )
    flush_consultation_steps(cid)

    with tempfile.TemporaryDirectory() as tmpdir:
        result = await _do_render(cid, tmpdir)
        with open(result["path"], "r", encoding="utf-8") as f:
            html = f.read()

    # Both source-book IDs appear inside book-badge spans somewhere
    assert re.search(
        r'<span class="book-badge"[^>]*>\[arsanjani_2026\]</span>', html
    ), "Expected arsanjani_2026 badge in rendered HTML"
    assert re.search(
        r'<span class="book-badge"[^>]*>\[gulli_2025\]</span>', html
    ), "Expected gulli_2025 badge in rendered HTML"


@pytest.mark.asyncio
async def test_unassessed_sibling_pattern_has_no_badge(consultation_cleanup):
    """Within a multi-book consultation, a pattern that was never assessed
    must not get a phantom badge. Only entries with source_book_id on the
    assessment carry one."""
    cid = consultation_cleanup("phase5c_sibling_001")
    _make_consultation(cid, project_id="proj_phase5c_sibling")

    # Only one assessment, with provenance.
    await log_pattern_assessment(
        consultation_id=cid,
        pattern_id="supervisor_architecture",
        pattern_name="Supervisor Architecture",
        status="implemented",
        source_book_id="gulli_2025",
    )
    flush_consultation_steps(cid)

    with tempfile.TemporaryDirectory() as tmpdir:
        result = await _do_render(cid, tmpdir)
        with open(result["path"], "r", encoding="utf-8") as f:
            html = f.read()

    # Multi-book mode is on (single assessment with provenance is enough
    # to flip the rollup), so badges are allowed. But the only badge
    # rendered against a scorecard pattern row should be gulli_2025 —
    # there should not be an arsanjani_2026 badge attached to a sibling.
    # Scenarios will still default to arsanjani_2026 so we can't assert
    # arsanjani_2026 is absent globally — but we can assert each
    # rendered badge corresponds to a known source_book_id.
    badges = re.findall(
        r'<span class="book-badge"[^>]*>\[([^\]]+)\]</span>', html
    )
    assert badges, "Expected at least one badge"
    # gulli_2025 must show up (the assessed pattern's badge in the scorecard)
    assert "gulli_2025" in badges
    # All emitted badges must be either the user-supplied gulli_2025 or
    # the 5b default arsanjani_2026 — no leakage of any other string.
    assert all(b in {"gulli_2025", "arsanjani_2026"} for b in badges), (
        f"Unexpected badge value(s): {set(badges) - {'gulli_2025', 'arsanjani_2026'}}"
    )


# --- stress-test side specifically -----------------------------------------


@pytest.mark.asyncio
async def test_stress_test_scenario_carries_badge(consultation_cleanup):
    """A multi-book consultation with a missing pattern that has a
    PATTERN_FAILURE_TEMPLATES entry (watchdog_timeout) → the rendered
    HTML contains a book-badge inside the stress-test scenario block,
    not just in the scorecard. Closes the unit-test gap that
    test_multi_book_consultation_emits_badges left open (its missing
    pattern didn't have a template, so no scenario rendered)."""
    cid = consultation_cleanup("phase5c_stress_001")
    _make_consultation(cid, project_id="proj_phase5c_stress")

    # Implemented arsanjani assessment to flip on multi-book mode...
    await log_pattern_assessment(
        consultation_id=cid,
        pattern_id="supervisor_architecture",
        pattern_name="Supervisor Architecture",
        status="implemented",
        source_book_id="arsanjani_2026",
    )
    # ...plus a missing watchdog_timeout (which IS in PATTERN_FAILURE_TEMPLATES)
    # so a scenario will be generated. Tag it gulli_2025 so we can assert the
    # specific badge that landed in the stress test.
    await log_pattern_assessment(
        consultation_id=cid,
        pattern_id="watchdog_timeout",
        pattern_name="Watchdog Timeout",
        status="missing",
        source_book_id="gulli_2025",
    )
    flush_consultation_steps(cid)

    with tempfile.TemporaryDirectory() as tmpdir:
        result = await _do_render(cid, tmpdir)
        assert result.get("scenarios_rendered", 0) >= 1, (
            "expected at least one scenario for missing watchdog_timeout"
        )
        with open(result["path"], "r", encoding="utf-8") as f:
            html = f.read()

    # Pull the stress-test region (everything after the SLOT had a
    # <details class="scenario") and check a badge is in there.
    # A simple substring check on '<details class="scenario' onwards.
    idx = html.find('<details class="scenario')
    assert idx != -1, "Expected at least one rendered scenario block"
    stress_html = html[idx:]
    assert re.search(
        r'<span class="book-badge"[^>]*>\[gulli_2025\]</span>', stress_html
    ), (
        "Expected the gulli_2025 badge to appear inside a scenario block "
        "(stress-test side of 5c, not just the scorecard)"
    )


# --- CSS class ships with the template -------------------------------------


@pytest.mark.asyncio
async def test_book_badge_css_class_present_in_template(consultation_cleanup):
    """The `.book-badge` CSS class definition ships in every rendered
    report (legacy or multi-book) so consumers don't need to inject it.
    Cheap safety net — if someone removes the CSS definition, this fails
    immediately."""
    cid = consultation_cleanup("phase5c_css_001")
    _make_consultation(cid)
    await log_pattern_assessment(
        consultation_id=cid,
        pattern_id="supervisor_architecture",
        pattern_name="Supervisor Architecture",
        status="implemented",
    )
    flush_consultation_steps(cid)

    with tempfile.TemporaryDirectory() as tmpdir:
        result = await _do_render(cid, tmpdir)
        with open(result["path"], "r", encoding="utf-8") as f:
            html = f.read()

    assert ".book-badge" in html, "Template should ship the .book-badge CSS class"
