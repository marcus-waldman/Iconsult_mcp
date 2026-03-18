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

    assert "maturity" in output
    assert "current" in output["maturity"]
    assert "target" in output["maturity"]
    assert output["patterns_rendered"] > 0
