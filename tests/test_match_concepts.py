"""Test that match_concepts returns relevant concepts for each architecture.

Each test case feeds an architectural description into match_concepts and
asserts that expected concept IDs appear in the results.
"""

import pytest

from tests.cases import CASES

from iconsult_mcp.tools.match_concepts import match_concepts


@pytest.fixture(params=CASES, ids=[c["id"] for c in CASES])
def case(request):
    return request.param


@pytest.mark.asyncio
async def test_match_returns_expected_concepts(case, consultation_cleanup):
    """Expected concepts appear in top-15 matches."""
    result = await match_concepts(case["description"], max_results=15)

    assert "error" not in result, result.get("error")
    consultation_cleanup(result["consultation_id"])

    matched_ids = {m["id"] for m in result["matched_concepts"]}

    for expected_id in case["expected_concepts"]:
        assert expected_id in matched_ids, (
            f"Case '{case['id']}': expected concept '{expected_id}' not in matches. "
            f"Got: {sorted(matched_ids)}"
        )


@pytest.mark.asyncio
async def test_match_determinism(consultation_cleanup):
    """Same description produces same concept ranking (fingerprint match)."""
    desc = CASES[0]["description"]

    r1 = await match_concepts(desc, max_results=10)
    r2 = await match_concepts(desc, max_results=10)

    consultation_cleanup(r1["consultation_id"])
    consultation_cleanup(r2["consultation_id"])

    assert r1["project_fingerprint"] == r2["project_fingerprint"]

    ids1 = [m["id"] for m in r1["matched_concepts"]]
    ids2 = [m["id"] for m in r2["matched_concepts"]]
    assert ids1 == ids2, "Same description should produce identical ranking"


@pytest.mark.asyncio
async def test_match_scores_are_sorted(case, consultation_cleanup):
    """Scores are in descending order."""
    result = await match_concepts(case["description"], max_results=15)
    consultation_cleanup(result["consultation_id"])

    scores = [m["score"] for m in result["matched_concepts"]]
    assert scores == sorted(scores, reverse=True), "Scores should be descending"
