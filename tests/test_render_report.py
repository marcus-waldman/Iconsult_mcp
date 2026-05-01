"""Test render_report tool — server-side HTML report rendering.

Creates a consultation with pattern assessments from test cases,
calls render_report with mock narrative content, and validates
the generated HTML structure.
"""

import json
import os
import tempfile

import pytest

from tests.cases import CASES

from iconsult_mcp.tools.match_concepts import match_concepts
from iconsult_mcp.tools.render_report import render_report
from iconsult_mcp.db import log_consultation_step


# Use the first case that has pattern_assessments
TEST_CASE = next(c for c in CASES if c.get("pattern_assessments"))

# Mock narrative content for render_report
MOCK_NARRATIVES = {
    "title": "Test Architecture Consultation",
    "executive_brief": (
        "This is a test system. It demonstrates strong foundational patterns "
        "including tool-based agent composition. The single most impactful "
        "opportunity is adding timeout protection. The recommended path forward "
        "is to implement watchdog timeouts and retry logic."
    ),
    "system_description": {
        "subtitle": "Test multi-agent system for financial research",
        "architecture": "Hierarchical supervisor with sub-analyst agents",
        "tech_stack": "Python, OpenAI Agents SDK",
        "coordination": "Tool-based agent composition with planning phase",
        "security": "No explicit auth layer",
    },
    "agents": [
        {
            "name": "Manager",
            "icon": "M",
            "color": "accent",
            "description": "Orchestrates sub-agents for financial research",
            "tools": ["run_analyst", "run_verifier"],
        },
        {
            "name": "Analyst",
            "icon": "A",
            "color": "green",
            "description": "Performs web search and financial analysis",
            "tools": ["web_search", "analyze_data"],
        },
    ],
    "diagram_current": (
        "flowchart TD\n"
        "  MGR[Manager] --> ANA[Analyst]\n"
        "  MGR --> VER[Verifier]\n"
        "  classDef existing fill:#0d948822,stroke:#0d9488\n"
        "  class MGR,ANA,VER existing"
    ),
    "diagram_target": (
        "flowchart TD\n"
        "  MGR[Manager] --> ANA[Analyst]\n"
        "  MGR --> VER[Verifier]\n"
        "  MGR --> WD[Watchdog]\n"
        "  classDef existing fill:#0d948822,stroke:#0d9488\n"
        "  classDef newcap fill:#d9770622,stroke:#d97706,stroke-dasharray:5 5\n"
        "  class MGR,ANA,VER existing\n"
        "  class WD newcap"
    ),
    "tooltips_current": {
        "MGR": {"title": "Manager", "desc": "Central orchestrator for research pipeline.", "ref": "manager.py"},
        "ANA": {"title": "Analyst", "desc": "Performs financial analysis with web search.", "ref": "agents/analyst.py"},
        "VER": {"title": "Verifier", "desc": "Quality gate for research output.", "ref": "agents/verifier.py"},
    },
    "tooltips_target": {
        "MGR": {"title": "Manager", "desc": "Orchestrator with timeout protection.", "ref": "manager.py"},
        "ANA": {"title": "Analyst", "desc": "Analyst with retry logic.", "ref": "agents/analyst.py"},
        "VER": {"title": "Verifier", "desc": "Verifier unchanged.", "ref": "agents/verifier.py"},
        "WD": {"title": "Watchdog", "desc": "NEW: Timeout protection for agent calls.", "ref": "Ch. 7, p. 212"},
    },
}


@pytest.mark.asyncio
async def test_render_report_produces_valid_html(consultation_cleanup):
    """render_report generates HTML with all expected sections."""
    result = await match_concepts(TEST_CASE["description"], max_results=5)
    cid = consultation_cleanup(result["consultation_id"])

    # Inject pattern assessments
    for pa in TEST_CASE["pattern_assessments"]:
        log_consultation_step(cid, "pattern_assessment", pa)

    # Use a temp directory for output
    with tempfile.TemporaryDirectory() as tmpdir:
        output = await render_report(
            consultation_id=cid,
            output_dir=tmpdir,
            **MOCK_NARRATIVES,
        )

        assert "error" not in output, output.get("error")
        assert "path" in output
        assert os.path.exists(output["path"])

        # Read the generated HTML
        with open(output["path"], "r", encoding="utf-8") as f:
            html = f.read()

    # Section structure checks
    assert "sections" in output
    assert "hero" in output["sections"]
    assert "exec_brief" in output["sections"]
    assert "maturity_banner" in output["sections"]
    assert "system_section" in output["sections"]
    assert "scorecard_rows" in output["sections"]
    assert "diagrams" in output["sections"]
    assert "recommendations" in output["sections"]
    assert "failure_chain" in output["sections"]
    assert "stress_test" in output["sections"]
    assert "footer" in output["sections"]
    assert "tooltip_scripts" in output["sections"]

    # HTML content checks
    assert "Test Architecture Consultation" in html
    assert "Executive Brief" in html
    assert "iConsult Architecture Review" in html

    # CSS is preserved
    assert ":root {" in html
    assert ".exec-brief {" in html
    assert ".mermaid-wrap {" in html

    # JS is preserved
    assert "mermaid.initialize" in html
    assert "function zoomDiagram" in html
    assert "anime({" in html

    # Mermaid diagrams are present (NOT html-escaped)
    assert "flowchart TD" in html
    assert "MGR[Manager]" in html

    # Tooltip JSON is present
    assert 'id="tooltips-current"' in html
    assert 'id="tooltips-target"' in html

    # Scorecard rows have expected CSS classes
    assert "status-badge" in html
    assert "has-tooltip" in html
    assert "data-tt-title" in html

    # Failure chain
    assert "chain-step" in html
    assert "Chain Coverage" in html

    # Footer
    assert cid in html


@pytest.mark.asyncio
async def test_render_report_escapes_user_content(consultation_cleanup):
    """User-provided text is HTML-escaped to prevent XSS."""
    result = await match_concepts(TEST_CASE["description"], max_results=5)
    cid = consultation_cleanup(result["consultation_id"])

    for pa in TEST_CASE["pattern_assessments"]:
        log_consultation_step(cid, "pattern_assessment", pa)

    xss_narratives = {
        **MOCK_NARRATIVES,
        "title": '<script>alert("xss")</script>Test',
        "executive_brief": 'Brief with <img onerror=alert(1)> injection',
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        output = await render_report(
            consultation_id=cid,
            output_dir=tmpdir,
            **xss_narratives,
        )

        assert "error" not in output, output.get("error")
        with open(output["path"], "r", encoding="utf-8") as f:
            html = f.read()

    # Script tag must be escaped in the title
    assert '<script>alert' not in html
    assert '&lt;script&gt;' in html

    # img tag must be escaped in the brief
    assert '<img onerror' not in html
    assert '&lt;img onerror' in html


@pytest.mark.asyncio
async def test_render_report_missing_consultation():
    """render_report returns error for non-existent consultation."""
    output = await render_report(
        consultation_id="nonexistent_consultation_id",
        **MOCK_NARRATIVES,
    )
    assert "error" in output


@pytest.mark.asyncio
async def test_render_report_no_assessments(consultation_cleanup):
    """render_report returns error when no pattern assessments exist."""
    result = await match_concepts(TEST_CASE["description"], max_results=5)
    cid = consultation_cleanup(result["consultation_id"])

    # Don't inject any assessments
    output = await render_report(
        consultation_id=cid,
        **MOCK_NARRATIVES,
    )
    assert "error" in output


@pytest.mark.asyncio
async def test_render_report_tooltip_json_is_valid(consultation_cleanup):
    """SVG tooltip JSON blocks are valid JSON."""
    result = await match_concepts(TEST_CASE["description"], max_results=5)
    cid = consultation_cleanup(result["consultation_id"])

    for pa in TEST_CASE["pattern_assessments"]:
        log_consultation_step(cid, "pattern_assessment", pa)

    with tempfile.TemporaryDirectory() as tmpdir:
        output = await render_report(
            consultation_id=cid,
            output_dir=tmpdir,
            **MOCK_NARRATIVES,
        )

        with open(output["path"], "r", encoding="utf-8") as f:
            html = f.read()

    # Extract and parse JSON from tooltip script blocks
    import re
    json_blocks = re.findall(
        r'<script type="application/json" id="tooltips-\w+">\s*(.*?)\s*</script>',
        html, re.DOTALL,
    )
    assert len(json_blocks) == 2, f"Expected 2 tooltip JSON blocks, got {len(json_blocks)}"

    for block in json_blocks:
        data = json.loads(block)
        assert isinstance(data, dict)
        for node_id, meta in data.items():
            assert "title" in meta
            assert "desc" in meta


@pytest.mark.asyncio
async def test_render_report_maturity_data(consultation_cleanup):
    """render_report return value includes maturity data."""
    result = await match_concepts(TEST_CASE["description"], max_results=5)
    cid = consultation_cleanup(result["consultation_id"])

    for pa in TEST_CASE["pattern_assessments"]:
        log_consultation_step(cid, "pattern_assessment", pa)

    with tempfile.TemporaryDirectory() as tmpdir:
        output = await render_report(
            consultation_id=cid,
            output_dir=tmpdir,
            **MOCK_NARRATIVES,
        )

    assert "categories_rendered" in output
    assert output["categories_rendered"] > 0


@pytest.mark.asyncio
async def test_render_report_enriched_tooltips_have_status(consultation_cleanup):
    """Enriched tooltips get status field when node matches an assessed pattern."""
    result = await match_concepts(TEST_CASE["description"], max_results=5)
    cid = consultation_cleanup(result["consultation_id"])

    for pa in TEST_CASE["pattern_assessments"]:
        log_consultation_step(cid, "pattern_assessment", pa)

    with tempfile.TemporaryDirectory() as tmpdir:
        output = await render_report(
            consultation_id=cid,
            output_dir=tmpdir,
            **MOCK_NARRATIVES,
        )

        with open(output["path"], "r", encoding="utf-8") as f:
            html_content = f.read()

    # Extract target tooltip JSON (WD = Watchdog which maps to watchdog_timeout)
    import re
    blocks = re.findall(
        r'<script type="application/json" id="tooltips-target">\s*(.*?)\s*</script>',
        html_content, re.DOTALL,
    )
    assert len(blocks) == 1
    target_data = json.loads(blocks[0])

    # WD node title is "Watchdog" which should match watchdog_timeout (missing)
    wd = target_data.get("WD", {})
    assert wd.get("status") == "missing", f"Expected 'missing' status for Watchdog, got {wd.get('status')}"
    # Missing pattern should have a failure teaser
    assert "failure_teaser" in wd, "Missing pattern should have failure_teaser"

    # MGR title is "Manager" — should match supervisor_architecture (implemented)
    # Check it in current tooltips
    blocks_cur = re.findall(
        r'<script type="application/json" id="tooltips-current">\s*(.*?)\s*</script>',
        html_content, re.DOTALL,
    )
    current_data = json.loads(blocks_cur[0])
    mgr = current_data.get("MGR", {})
    # Manager → Supervisor Architecture match may or may not happen depending on
    # fuzzy matching. At minimum, original fields are preserved.
    assert mgr.get("title") == "Manager"
    assert mgr.get("desc") == "Central orchestrator for research pipeline."


@pytest.mark.asyncio
async def test_render_report_enriched_tooltips_no_match_passthrough(consultation_cleanup):
    """Tooltip nodes that don't match any pattern keep original fields only."""
    result = await match_concepts(TEST_CASE["description"], max_results=5)
    cid = consultation_cleanup(result["consultation_id"])

    for pa in TEST_CASE["pattern_assessments"]:
        log_consultation_step(cid, "pattern_assessment", pa)

    # Use tooltips with a node that won't match any pattern
    custom_tooltips = {
        "tooltips_current": {
            "XYZ": {"title": "Totally Unique Widget", "desc": "No match.", "ref": "n/a"},
        },
        "tooltips_target": {
            "XYZ": {"title": "Totally Unique Widget", "desc": "No match.", "ref": "n/a"},
        },
    }
    narratives = {**MOCK_NARRATIVES, **custom_tooltips}

    with tempfile.TemporaryDirectory() as tmpdir:
        output = await render_report(
            consultation_id=cid,
            output_dir=tmpdir,
            **narratives,
        )

        with open(output["path"], "r", encoding="utf-8") as f:
            html_content = f.read()

    import re
    blocks = re.findall(
        r'<script type="application/json" id="tooltips-current">\s*(.*?)\s*</script>',
        html_content, re.DOTALL,
    )
    data = json.loads(blocks[0])
    xyz = data.get("XYZ", {})

    # Original fields preserved, no enrichment fields added
    assert xyz.get("title") == "Totally Unique Widget"
    assert xyz.get("desc") == "No match."
    assert "status" not in xyz
    assert "indicators" not in xyz
    assert "failure_teaser" not in xyz


# --- B3: tooltip shape validation ----------------------------------------


@pytest.mark.asyncio
async def test_render_report_rejects_string_tooltips_current(consultation_cleanup):
    """Bug #3 regression: passing string values for tooltips_current must
    return a clean error, not crash deep in _enrich_tooltips with a cryptic
    ``ValueError: dictionary update sequence element #0 has length 1; 2 is
    required``."""
    result = await match_concepts(TEST_CASE["description"], max_results=5)
    cid = consultation_cleanup(result["consultation_id"])

    for pa in TEST_CASE["pattern_assessments"]:
        log_consultation_step(cid, "pattern_assessment", pa)

    bad_narratives = {
        **MOCK_NARRATIVES,
        "tooltips_current": {"MGR": "Manager (string instead of dict)"},
    }

    output = await render_report(consultation_id=cid, **bad_narratives)
    assert "error" in output
    err = output["error"]
    assert "tooltips_current" in err
    assert "MGR" in err
    assert "str" in err  # the bad type is reported


@pytest.mark.asyncio
async def test_render_report_rejects_string_tooltips_target(consultation_cleanup):
    """Same shape check, but for tooltips_target."""
    result = await match_concepts(TEST_CASE["description"], max_results=5)
    cid = consultation_cleanup(result["consultation_id"])

    for pa in TEST_CASE["pattern_assessments"]:
        log_consultation_step(cid, "pattern_assessment", pa)

    bad_narratives = {
        **MOCK_NARRATIVES,
        "tooltips_target": {"WD": "Watchdog (bad shape)"},
    }

    output = await render_report(consultation_id=cid, **bad_narratives)
    assert "error" in output
    err = output["error"]
    assert "tooltips_target" in err
    assert "WD" in err


@pytest.mark.asyncio
async def test_render_report_rejects_non_dict_tooltips(consultation_cleanup):
    """Passing a list (or any non-dict) for tooltips_current must error
    cleanly rather than crashing on iteration / ``.items()``."""
    result = await match_concepts(TEST_CASE["description"], max_results=5)
    cid = consultation_cleanup(result["consultation_id"])

    for pa in TEST_CASE["pattern_assessments"]:
        log_consultation_step(cid, "pattern_assessment", pa)

    bad_narratives = {
        **MOCK_NARRATIVES,
        "tooltips_current": ["not", "a", "dict"],
    }

    output = await render_report(consultation_id=cid, **bad_narratives)
    assert "error" in output
    assert "tooltips_current" in output["error"]
    assert "list" in output["error"]


@pytest.mark.asyncio
async def test_render_report_accepts_empty_tooltip_dicts(consultation_cleanup):
    """Empty tooltip dicts are valid — every entry is shape-correct (zero
    entries to check). Diagram nodes simply get no enrichment."""
    result = await match_concepts(TEST_CASE["description"], max_results=5)
    cid = consultation_cleanup(result["consultation_id"])

    for pa in TEST_CASE["pattern_assessments"]:
        log_consultation_step(cid, "pattern_assessment", pa)

    narratives = {
        **MOCK_NARRATIVES,
        "tooltips_current": {},
        "tooltips_target": {},
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        output = await render_report(
            consultation_id=cid,
            output_dir=tmpdir,
            **narratives,
        )

    assert "error" not in output, output.get("error")
    assert "path" in output
