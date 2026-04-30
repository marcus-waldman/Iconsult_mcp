"""Phase 3b — start_project tool tests.

Verifies project creation, internal triage fallback, deterministic
project_id derivation, idempotency, and input validation.

With one book registered the internal-triage path is degenerate but its
plumbing (triage call → ranked IDs → persisted) is still exercised. The
tests gain teeth in Phase 3c when a second book lands.
"""

from __future__ import annotations

import pytest

from iconsult_mcp.db import get_project
from iconsult_mcp.tools.projects import _derive_project_id, start_project


_AGENTIC_DESCRIPTION = (
    "We are building a multi-agent system where specialized AI agents "
    "coordinate to handle complex business workflows. The architecture "
    "needs robust fault tolerance, supervisor patterns, and human-in-the-loop "
    "escalation."
)


# --- happy path ------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_project_with_explicit_triaged_book_ids(project_cleanup):
    register_project, _ = project_cleanup
    result = await start_project(
        name="Explicit Triage Test",
        project_description=_AGENTIC_DESCRIPTION,
        triaged_book_ids=["arsanjani_2026"],
    )
    register_project(result["project_id"])

    assert "error" not in result, result.get("error")
    assert result["project"]["triaged_book_ids"] == ["arsanjani_2026"]
    # Internal triage is skipped when explicit IDs are supplied
    assert result["triage"] is None
    assert result["project"]["unified_kg_built_at"] is None


@pytest.mark.asyncio
async def test_start_project_runs_internal_triage_when_omitted(project_cleanup):
    """When triaged_book_ids is omitted, triage_books is called and stored."""
    register_project, _ = project_cleanup
    result = await start_project(
        name="Internal Triage Test",
        project_description=_AGENTIC_DESCRIPTION,
        triage_threshold=0.0,  # ensure the single book lands above threshold
    )
    register_project(result["project_id"])

    assert "error" not in result, result.get("error")
    assert result["triage"] is not None
    assert "ranked_books" in result["triage"]
    # Whatever triage returned should be persisted on the project row
    triaged = result["project"]["triaged_book_ids"]
    expected = [b["id"] for b in result["triage"]["ranked_books"]]
    assert triaged == expected
    assert "arsanjani_2026" in triaged


@pytest.mark.asyncio
async def test_start_project_response_shape(project_cleanup):
    register_project, _ = project_cleanup
    result = await start_project(
        name="Shape Test",
        project_description=_AGENTIC_DESCRIPTION,
        triaged_book_ids=["arsanjani_2026"],
    )
    register_project(result["project_id"])

    assert "project_id" in result
    assert "project" in result
    assert "triage" in result
    for key in [
        "id", "name", "description", "triaged_book_ids",
        "unified_kg_built_at", "created_at",
    ]:
        assert key in result["project"], f"missing project field: {key}"


# --- determinism + idempotency --------------------------------------------


@pytest.mark.asyncio
async def test_start_project_id_is_deterministic(project_cleanup):
    """Same (name, description) always produces the same project_id."""
    register_project, _ = project_cleanup
    r1 = await start_project(
        name="Idempotent Project",
        project_description=_AGENTIC_DESCRIPTION,
        triaged_book_ids=["arsanjani_2026"],
    )
    r2 = await start_project(
        name="Idempotent Project",
        project_description=_AGENTIC_DESCRIPTION,
        triaged_book_ids=["arsanjani_2026"],
    )
    register_project(r1["project_id"])
    assert r1["project_id"] == r2["project_id"]


@pytest.mark.asyncio
async def test_start_project_different_descriptions_yield_different_ids(project_cleanup):
    register_project, _ = project_cleanup
    r1 = await start_project(
        name="Same Name",
        project_description="description one",
        triaged_book_ids=["arsanjani_2026"],
    )
    r2 = await start_project(
        name="Same Name",
        project_description="description two",
        triaged_book_ids=["arsanjani_2026"],
    )
    register_project(r1["project_id"])
    register_project(r2["project_id"])
    assert r1["project_id"] != r2["project_id"]


@pytest.mark.asyncio
async def test_start_project_idempotent_re_run_updates_triage(project_cleanup):
    """Calling twice with same args + different triaged_book_ids overwrites."""
    register_project, _ = project_cleanup
    r1 = await start_project(
        name="Reupsert Test",
        project_description=_AGENTIC_DESCRIPTION,
        triaged_book_ids=["arsanjani_2026"],
    )
    r2 = await start_project(
        name="Reupsert Test",
        project_description=_AGENTIC_DESCRIPTION,
        triaged_book_ids=[],  # explicit override
    )
    register_project(r1["project_id"])
    assert r1["project_id"] == r2["project_id"]
    # Latest write wins — DB reflects the second call
    persisted = get_project(r2["project_id"])
    assert persisted["triaged_book_ids"] == []


@pytest.mark.asyncio
async def test_start_project_user_supplied_project_id(project_cleanup):
    register_project, _ = project_cleanup
    pid = "test_proj_user_supplied_pid"
    register_project(pid)
    result = await start_project(
        name="User-Supplied ID Test",
        project_description=_AGENTIC_DESCRIPTION,
        triaged_book_ids=["arsanjani_2026"],
        project_id=pid,
    )
    assert result["project_id"] == pid
    assert get_project(pid) is not None


def test_derive_project_id_format_and_stability():
    """Derived IDs use the proj_<12hex> format and are deterministic."""
    pid_1 = _derive_project_id("Foo", "bar baz")
    pid_2 = _derive_project_id("Foo", "bar baz")
    assert pid_1 == pid_2
    assert pid_1.startswith("proj_")
    assert len(pid_1) == len("proj_") + 12


# --- input validation ------------------------------------------------------


@pytest.mark.asyncio
async def test_start_project_rejects_blank_name():
    r1 = await start_project(name="", project_description=_AGENTIC_DESCRIPTION)
    r2 = await start_project(name="   ", project_description=_AGENTIC_DESCRIPTION)
    assert "error" in r1
    assert "error" in r2


@pytest.mark.asyncio
async def test_start_project_rejects_blank_description():
    r1 = await start_project(name="Has Name", project_description="")
    r2 = await start_project(name="Has Name", project_description="   ")
    assert "error" in r1
    assert "error" in r2


@pytest.mark.asyncio
async def test_start_project_rejects_malformed_triaged_book_ids():
    """Non-list-of-strings triaged_book_ids is rejected with a clear error."""
    r = await start_project(
        name="Bad Triage Type",
        project_description=_AGENTIC_DESCRIPTION,
        triaged_book_ids=[1, 2, 3],  # not strings
    )
    assert "error" in r


# --- triage threshold behaviour -------------------------------------------


@pytest.mark.asyncio
async def test_start_project_high_threshold_yields_empty_triage(project_cleanup):
    """Threshold above any plausible cosine score persists empty triaged_book_ids.

    The project is still created — `build_project_kg` (3c) is responsible for
    refusing to run on a zero-book project, not `start_project`.
    """
    register_project, _ = project_cleanup
    result = await start_project(
        name="Empty Triage Test",
        project_description="An off-topic recipe collection app",
        triage_threshold=0.99,
    )
    register_project(result["project_id"])

    assert "error" not in result, result.get("error")
    assert result["project"]["triaged_book_ids"] == []
    assert result["triage"]["total_above_threshold"] == 0
