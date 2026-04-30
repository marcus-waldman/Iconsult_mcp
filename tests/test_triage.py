"""Phase 2b — triage_books tool tests.

With only arsanjani_2026 in the corpus the relative-ranking surface is
degenerate: every above-threshold result lists exactly one book. The
meaningful tests at this stage are determinism, threshold filtering,
relevance signal vs. off-topic description, response shape, and input
validation. Phase 6 onboards a second book and these tests gain teeth.
"""

import pytest

from iconsult_mcp.tools.triage import triage_books


_AGENTIC_DESCRIPTION = (
    "We are building a multi-agent system where specialized AI agents "
    "coordinate to handle complex business workflows. The architecture "
    "needs robust fault tolerance, supervisor patterns, and human-in-the-loop "
    "escalation. We want explainability for compliance reasons and the "
    "ability to recover gracefully when individual agents fail or stall."
)


@pytest.mark.asyncio
async def test_triage_returns_arsanjani_for_agentic_description():
    """A clearly-relevant project description matches arsanjani_2026 above threshold."""
    result = await triage_books(_AGENTIC_DESCRIPTION, top_k=5, threshold=0.4)

    assert "error" not in result, result.get("error")
    assert result["total_above_threshold"] >= 1
    ids = [b["id"] for b in result["ranked_books"]]
    assert "arsanjani_2026" in ids


@pytest.mark.asyncio
async def test_triage_determinism():
    """Same description must produce identical ranking and scores."""
    r1 = await triage_books(_AGENTIC_DESCRIPTION, top_k=5)
    r2 = await triage_books(_AGENTIC_DESCRIPTION, top_k=5)

    assert "error" not in r1
    assert "error" not in r2

    pairs1 = [(b["id"], b["score"]) for b in r1["ranked_books"]]
    pairs2 = [(b["id"], b["score"]) for b in r2["ranked_books"]]
    assert pairs1 == pairs2


@pytest.mark.asyncio
async def test_triage_threshold_filter_excludes_when_too_high():
    """A threshold above any plausible cosine score returns an empty list."""
    result = await triage_books(_AGENTIC_DESCRIPTION, top_k=5, threshold=0.99)

    assert "error" not in result
    assert result["ranked_books"] == []
    assert result["total_above_threshold"] == 0


@pytest.mark.asyncio
async def test_triage_top_k_caps_results():
    """top_k=1 returns at most 1 book."""
    result = await triage_books(_AGENTIC_DESCRIPTION, top_k=1, threshold=0.0)
    assert "error" not in result
    assert len(result["ranked_books"]) <= 1


@pytest.mark.asyncio
async def test_triage_relevance_signal():
    """An agentic-architecture description scores higher than an off-topic one.

    With one book registered both queries hit the same book, but the cosine
    score against the agentic summary should be meaningfully higher for the
    relevant description than for an unrelated one.
    """
    relevant = await triage_books(_AGENTIC_DESCRIPTION, top_k=1, threshold=0.0)
    irrelevant = await triage_books(
        "A recipe collection app for organizing family cooking traditions and "
        "weekly meal planning. We want shopping list generation and a clean "
        "mobile UI.",
        top_k=1,
        threshold=0.0,
    )

    assert len(relevant["ranked_books"]) == 1
    assert len(irrelevant["ranked_books"]) == 1

    relevant_score = relevant["ranked_books"][0]["score"]
    irrelevant_score = irrelevant["ranked_books"][0]["score"]
    assert relevant_score > irrelevant_score, (
        f"Agentic description ({relevant_score}) should outscore "
        f"recipe app ({irrelevant_score})"
    )


@pytest.mark.asyncio
async def test_triage_empty_description_errors():
    """Blank or empty description returns an error response."""
    r_empty = await triage_books("")
    r_blank = await triage_books("   ")
    assert "error" in r_empty
    assert "error" in r_blank


@pytest.mark.asyncio
async def test_triage_response_shape():
    """Response carries expected fields per book."""
    result = await triage_books(_AGENTIC_DESCRIPTION, top_k=1, threshold=0.0)

    assert "ranked_books" in result
    assert "total_above_threshold" in result
    assert "threshold" in result

    if result["ranked_books"]:
        b = result["ranked_books"][0]
        for key in ["id", "title", "altitude", "is_oracle", "score"]:
            assert key in b, f"missing key: {key}"
        assert isinstance(b["score"], float)
        assert isinstance(b["is_oracle"], bool)
