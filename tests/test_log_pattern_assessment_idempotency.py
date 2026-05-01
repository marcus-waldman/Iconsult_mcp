"""B1 — log_pattern_assessment idempotency at the read layer.

`log_consultation_step` is intentionally append-only (audit / critique need
the full history), so two calls to ``log_pattern_assessment`` with the same
``(consultation_id, pattern_id)`` write two rows to ``consultations.steps``.
The reader ``score_architecture._get_pattern_assessments`` collapses those
rows back to one assessment per canonical pattern_id with **latest wins**
semantics — a re-log supersedes the earlier value.

This file pins that contract at three layers:
  - the reader returns the latest assessment for a duplicated pattern_id
  - ``score_architecture`` reflects the second status (not the first)
  - book-prefixed pattern_ids re-logged by their canonical form still
    resolve to one assessment under the rubric-canonical key
"""

from __future__ import annotations

import pytest

from iconsult_mcp.db import (
    create_consultation,
    flush_consultation_steps,
    get_consultation,
)
from iconsult_mcp.tools.log_pattern_assessment import log_pattern_assessment
from iconsult_mcp.tools.score_architecture import (
    _get_pattern_assessments,
    score_architecture,
)


def _make_consultation(cid: str, project_id: str | None = None) -> str:
    create_consultation(
        consultation_id=cid,
        fingerprint=f"fp-{cid}",
        description="idempotency test",
        concept_ids=[],
        scores=[],
        project_id=project_id,
    )
    return cid


# --- reader-level: latest wins ---------------------------------------------


@pytest.mark.asyncio
async def test_reader_returns_latest_assessment_on_duplicate(consultation_cleanup):
    """Logging the same pattern twice → reader keeps the second (latest) one."""
    cid = consultation_cleanup("idempotency_reader_001")
    _make_consultation(cid)

    await log_pattern_assessment(
        consultation_id=cid,
        pattern_id="supervisor_architecture",
        pattern_name="Supervisor Architecture",
        status="missing",
        evidence="first log — not yet present",
    )
    await log_pattern_assessment(
        consultation_id=cid,
        pattern_id="supervisor_architecture",
        pattern_name="Supervisor Architecture",
        status="implemented",
        evidence="second log — found supervisor in code",
    )

    flush_consultation_steps(cid)
    record = get_consultation(cid)

    # Both rows are still in the append-only step log (audit invariant)
    pa_rows = [s for s in record["steps"] if s.get("type") == "pattern_assessment"]
    assert len(pa_rows) == 2

    # But the reader collapses to one canonical entry, latest wins
    assessments = _get_pattern_assessments(record)
    assert "supervisor_architecture" in assessments
    a = assessments["supervisor_architecture"]
    assert a["status"] == "implemented"
    assert "found supervisor in code" in a["evidence"]


# --- score_architecture: latest status drives the rating -------------------


@pytest.mark.asyncio
async def test_score_architecture_reflects_latest_status_on_duplicate(
    consultation_cleanup,
):
    """A re-log from missing → implemented must move the score the same way
    a single 'implemented' assessment would. The first 'missing' must not
    linger in the rating."""
    cid_relog = consultation_cleanup("idempotency_score_relog_001")
    cid_single = consultation_cleanup("idempotency_score_single_001")
    _make_consultation(cid_relog)
    _make_consultation(cid_single)

    # cid_relog: log missing first, then implemented (the bug scenario)
    await log_pattern_assessment(
        consultation_id=cid_relog,
        pattern_id="supervisor_architecture",
        pattern_name="Supervisor Architecture",
        status="missing",
    )
    await log_pattern_assessment(
        consultation_id=cid_relog,
        pattern_id="supervisor_architecture",
        pattern_name="Supervisor Architecture",
        status="implemented",
    )

    # cid_single: log implemented once (the control)
    await log_pattern_assessment(
        consultation_id=cid_single,
        pattern_id="supervisor_architecture",
        pattern_name="Supervisor Architecture",
        status="implemented",
    )

    score_relog = await score_architecture(cid_relog)
    score_single = await score_architecture(cid_single)

    assert "error" not in score_relog
    assert "error" not in score_single

    # The category ratings must match: a re-log to implemented produces the
    # same scoring outcome as a single implemented assessment.
    relog_ratings = {k: v["rating"] for k, v in score_relog["categories"].items()}
    single_ratings = {k: v["rating"] for k, v in score_single["categories"].items()}
    assert relog_ratings == single_ratings

    # Spot-check: coordination (where supervisor_architecture lives) should
    # not be 'not_started' since we logged an implemented assessment
    assert score_relog["categories"]["coordination"]["rating"] != "not_started"


# --- book-prefixed re-log: aliases to canonical, latest still wins ---------


@pytest.mark.asyncio
async def test_book_prefixed_relog_collapses_to_canonical_latest_wins(
    consultation_cleanup,
):
    """Logging `gulli_2025__supervisor_architecture` then plain
    `supervisor_architecture` (different raw IDs, same canonical) should
    collapse to one canonical entry with the latest status."""
    cid = consultation_cleanup("idempotency_aliased_001")
    _make_consultation(cid)

    # First: book-prefixed, missing
    await log_pattern_assessment(
        consultation_id=cid,
        pattern_id="gulli_2025__supervisor_architecture",
        pattern_name="Supervisor Architecture",
        status="missing",
        source_book_id="gulli_2025",
    )
    # Second: canonical form, implemented
    await log_pattern_assessment(
        consultation_id=cid,
        pattern_id="supervisor_architecture",
        pattern_name="Supervisor Architecture",
        status="implemented",
        source_book_id="arsanjani_2026",
    )

    flush_consultation_steps(cid)
    record = get_consultation(cid)
    assessments = _get_pattern_assessments(record)

    # One canonical entry, latest wins
    canonical = assessments.get("supervisor_architecture")
    assert canonical is not None
    assert canonical["status"] == "implemented"
    assert canonical["source_book_id"] == "arsanjani_2026"
