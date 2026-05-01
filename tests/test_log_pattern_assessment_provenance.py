"""Phase 4d — log_pattern_assessment provenance fields.

Covers:
- `source_book_id` and `canonical_concept_id` persist on the step_data when
  provided, surface in the response, are absent when omitted (backwards
  compatible).
- The provenance fields pass through `_get_pattern_assessments` (the
  reader used by score_architecture / failure_scenarios / implementation_plan).
- `score_architecture` is unchanged by provenance fields — assessments with
  and without provenance score identically because score_architecture keys on
  `pattern_id` resolved through the rubric aliases.
- A book-prefixed pattern_id (e.g., `gulli_2025__supervisor_architecture`)
  still aliases through `normalize_pattern_id` correctly when source_book_id
  is supplied alongside.
"""

from __future__ import annotations

import pytest

from iconsult_mcp.db import (
    create_consultation,
    flush_consultation_steps,
    get_consultation,
    get_pattern_assessments,
)
from iconsult_mcp.tools.log_pattern_assessment import log_pattern_assessment
from iconsult_mcp.tools.score_architecture import (
    _get_pattern_assessments,
    score_architecture,
)


def _make_consultation(cid: str, project_id: str | None = None) -> str:
    """Insert a minimal consultation row so log_pattern_assessment can write to it."""
    create_consultation(
        consultation_id=cid,
        fingerprint=f"fp-{cid}",
        description="provenance test",
        concept_ids=[],
        scores=[],
        project_id=project_id,
    )
    return cid


# --- backwards compatibility -----------------------------------------------


@pytest.mark.asyncio
async def test_log_pattern_assessment_no_provenance_unchanged(consultation_cleanup):
    """Calling without provenance fields → step_data has neither key, response
    has neither key. Existing callers untouched."""
    cid = consultation_cleanup("provenance_legacy_001")
    _make_consultation(cid)

    result = await log_pattern_assessment(
        consultation_id=cid,
        pattern_id="supervisor_architecture",
        pattern_name="Supervisor Architecture",
        status="implemented",
    )
    assert result["logged"] is True
    assert "source_book_id" not in result
    assert "canonical_concept_id" not in result

    flush_consultation_steps(cid)
    record = get_consultation(cid)
    pa = next(s for s in record["steps"] if s.get("type") == "pattern_assessment")
    assert "source_book_id" not in pa
    assert "canonical_concept_id" not in pa


# --- provenance happy path -------------------------------------------------


@pytest.mark.asyncio
async def test_log_pattern_assessment_persists_provenance(consultation_cleanup):
    """Provenance fields land on step_data and surface in the response."""
    cid = consultation_cleanup("provenance_persist_001")
    _make_consultation(cid, project_id="proj_phase4d_test")

    result = await log_pattern_assessment(
        consultation_id=cid,
        pattern_id="supervisor_architecture",
        pattern_name="Supervisor Architecture",
        status="implemented",
        source_book_id="gulli_2025",
        canonical_concept_id="proj_phase4d_test__multi_agent_topology",
    )
    assert result["logged"] is True
    assert result["source_book_id"] == "gulli_2025"
    assert result["canonical_concept_id"] == "proj_phase4d_test__multi_agent_topology"

    flush_consultation_steps(cid)
    record = get_consultation(cid)
    pa = next(s for s in record["steps"] if s.get("type") == "pattern_assessment")
    assert pa["source_book_id"] == "gulli_2025"
    assert pa["canonical_concept_id"] == "proj_phase4d_test__multi_agent_topology"


@pytest.mark.asyncio
async def test_provenance_passes_through_pattern_assessment_reader(
    consultation_cleanup,
):
    """The score_architecture / failure_scenarios reader surfaces provenance."""
    cid = consultation_cleanup("provenance_reader_001")
    _make_consultation(cid, project_id="proj_phase4d_reader")

    await log_pattern_assessment(
        consultation_id=cid,
        pattern_id="supervisor_architecture",
        pattern_name="Supervisor Architecture",
        status="implemented",
        source_book_id="arsanjani_2026",
        canonical_concept_id="proj_phase4d_reader__supervisor",
    )

    flush_consultation_steps(cid)
    record = get_consultation(cid)
    assessments = _get_pattern_assessments(record)
    # Keyed by canonical pattern_id (rubric ID)
    assert "supervisor_architecture" in assessments
    a = assessments["supervisor_architecture"]
    assert a["source_book_id"] == "arsanjani_2026"
    assert a["canonical_concept_id"] == "proj_phase4d_reader__supervisor"

    # db.get_pattern_assessments (the lower-level helper) also surfaces them
    rows = get_pattern_assessments(cid)
    assert len(rows) == 1
    assert rows[0]["source_book_id"] == "arsanjani_2026"
    assert rows[0]["canonical_concept_id"] == "proj_phase4d_reader__supervisor"


# --- score_architecture invariance -----------------------------------------


@pytest.mark.asyncio
async def test_score_architecture_invariant_under_provenance(consultation_cleanup):
    """An assessment with provenance fields scores identically to one without."""
    # Two parallel consultations, identical assessments except for provenance
    cid_plain = consultation_cleanup("provenance_score_plain_001")
    cid_prov = consultation_cleanup("provenance_score_prov_001")
    _make_consultation(cid_plain)
    _make_consultation(cid_prov, project_id="proj_phase4d_score")

    pattern_id = "supervisor_architecture"
    pattern_name = "Supervisor Architecture"

    await log_pattern_assessment(
        consultation_id=cid_plain,
        pattern_id=pattern_id,
        pattern_name=pattern_name,
        status="implemented",
    )
    await log_pattern_assessment(
        consultation_id=cid_prov,
        pattern_id=pattern_id,
        pattern_name=pattern_name,
        status="implemented",
        source_book_id="gulli_2025",
        canonical_concept_id="proj_phase4d_score__supervisor",
    )

    score_plain = await score_architecture(cid_plain)
    score_prov = await score_architecture(cid_prov)

    assert "error" not in score_plain
    assert "error" not in score_prov

    # Categories ratings should match (provenance doesn't influence scoring)
    plain_ratings = {k: v["rating"] for k, v in score_plain["categories"].items()}
    prov_ratings = {k: v["rating"] for k, v in score_prov["categories"].items()}
    assert plain_ratings == prov_ratings


# --- book-prefixed pattern_id still aliases -------------------------------


@pytest.mark.asyncio
async def test_book_prefixed_pattern_id_still_aliases_through_rubric(
    consultation_cleanup,
):
    """A `{book_id}__` prefixed pattern_id alongside source_book_id still
    resolves through normalize_pattern_id → rubric pattern."""
    cid = consultation_cleanup("provenance_aliased_pid_001")
    _make_consultation(cid)

    result = await log_pattern_assessment(
        consultation_id=cid,
        pattern_id="gulli_2025__supervisor_architecture",  # book-prefixed
        pattern_name="Supervisor Architecture",
        status="implemented",
        source_book_id="gulli_2025",
    )
    # canonical_pid in the response is the rubric-canonical form
    assert result["pattern_id"] == "supervisor_architecture"
    assert result["category"]  # rubric category resolved
    assert result["level"]     # rubric level resolved

    flush_consultation_steps(cid)
    record = get_consultation(cid)
    assessments = _get_pattern_assessments(record)
    assert "supervisor_architecture" in assessments
    a = assessments["supervisor_architecture"]
    assert a["source_book_id"] == "gulli_2025"


@pytest.mark.asyncio
async def test_provenance_only_one_field_supplied(consultation_cleanup):
    """Either provenance field can be supplied without the other."""
    cid = consultation_cleanup("provenance_partial_001")
    _make_consultation(cid)

    # Only source_book_id
    r1 = await log_pattern_assessment(
        consultation_id=cid,
        pattern_id="supervisor_architecture",
        pattern_name="Supervisor Architecture",
        status="missing",
        source_book_id="arsanjani_2026",
    )
    assert r1["source_book_id"] == "arsanjani_2026"
    assert "canonical_concept_id" not in r1

    flush_consultation_steps(cid)
    record = get_consultation(cid)
    pa = record["steps"][-1]
    assert pa["source_book_id"] == "arsanjani_2026"
    assert "canonical_concept_id" not in pa
