"""Server-side HTML report renderer.

Loads the slot-based template, pulls structured data from DuckDB via
score_architecture / generate_failure_scenarios / consultation_report,
merges with Claude-provided narrative content, and writes a complete
HTML report to disk.  No LLM calls — pure template rendering.
"""

import html
import json
import os
from datetime import datetime, timezone

from iconsult_mcp.db import get_connection
from iconsult_mcp.tools.score_architecture import score_architecture
from iconsult_mcp.tools.rubric_data import normalize_pattern_id, _PATTERN_ID_ALIASES
from iconsult_mcp.tools.failure_scenarios import generate_failure_scenarios
from iconsult_mcp.tools.consultation_report import consultation_report

# ---------------------------------------------------------------------------
# Template loading
# ---------------------------------------------------------------------------

_TEMPLATE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "templates",
)
_TEMPLATE_FILE = os.path.join(_TEMPLATE_DIR, "consultation-report-template.html")

# Agent color presets — maps a color name to (bg CSS var, text CSS var)
_AGENT_COLORS: dict[str, tuple[str, str]] = {
    "accent": ("var(--accent-dim)", "var(--accent)"),
    "green": ("var(--green-dim)", "var(--green)"),
    "blue": ("var(--blue-dim)", "var(--blue)"),
    "amber": ("var(--amber-dim)", "var(--amber)"),
    "red": ("var(--red-dim)", "var(--red)"),
    "purple": ("var(--purple-dim)", "var(--purple)"),
}

# Status → CSS class mapping
_STATUS_CSS: dict[str, str] = {
    "implemented": "status-implemented",
    "partial": "status-partial",
    "missing": "status-missing",
    "not_applicable": "status-na",
    "not_assessed": "status-na",
}

# Status → display label
_STATUS_LABEL: dict[str, str] = {
    "implemented": "Implemented",
    "partial": "Partial",
    "missing": "Missing",
    "not_applicable": "N/A",
    "not_assessed": "Not Assessed",
}

# Severity → CSS class
_SEVERITY_CSS: dict[str, str] = {
    "CRITICAL": "severity-critical",
    "WARNING": "severity-warning",
    "INFO": "severity-info",
}

# Phase → CSS class
_PHASE_CSS: dict[int, str] = {1: "phase-1", 2: "phase-2", 3: "phase-3"}


# ---------------------------------------------------------------------------
# Render helpers — each returns an HTML fragment string
# ---------------------------------------------------------------------------

def _esc(text: str) -> str:
    """HTML-escape text, preserving None as empty string."""
    if not text:
        return ""
    return html.escape(str(text))


def _render_hero(title: str, date: str) -> str:
    t = _esc(title)
    return (
        '  <div class="hero-badge ani">iConsult Architecture Review</div>\n'
        f'  <h1 class="ani">{t}</h1>\n'
        f'  <p class="subtitle ani">Based on <em>Agentic Architectural Patterns for '
        f'Building Multi-Agent Systems</em> (Arsanjani &amp; Bustos, Packt 2026). '
        f'Consultation date: {_esc(date)}.</p>'
    )


def _render_exec_brief(text: str) -> str:
    # Allow <strong> tags in the brief — escape everything else
    safe = _esc(text).replace("&lt;strong&gt;", "<strong>").replace("&lt;/strong&gt;", "</strong>")
    return f'  <strong>Executive Brief</strong><br>\n  {safe}'


# Rating → CSS class
_RATING_CSS: dict[str, str] = {
    "not_started": "rating-not-started",
    "emerging": "rating-emerging",
    "established": "rating-established",
    "mature": "rating-mature",
}

_RATING_LABEL: dict[str, str] = {
    "not_started": "Not Started",
    "emerging": "Emerging",
    "established": "Established",
    "mature": "Mature",
}


def _render_maturity_banner(categories: dict) -> str:
    lines = []
    lines.append('<div class="maturity-banner ani">')
    lines.append('  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;width:100%;">')

    for cat_key, cat in categories.items():
        rating = cat.get("rating", "not_started")
        css = _RATING_CSS.get(rating, "rating-not-started")
        label = _RATING_LABEL.get(rating, rating.title())
        name = cat.get("name", cat_key)

        lines.append(f'    <div class="category-badge {css}" style="text-align:center;padding:12px;border-radius:8px;">')
        lines.append(f'      <div style="font-weight:700;font-size:0.95rem;">{_esc(name)}</div>')
        lines.append(f'      <div class="status-badge {css}" style="margin-top:6px;">{_esc(label)}</div>')
        lines.append('    </div>')

    lines.append('  </div>')
    lines.append('</div>')
    return "\n".join(lines)


def _render_system_section(system_description: dict, agents: list[dict]) -> str:
    sd = system_description
    lines = []

    # Subtitle
    subtitle = _esc(sd.get("subtitle", ""))
    if subtitle:
        lines.append(f'<p class="subtitle">{subtitle}</p>')

    # 2x2 card grid
    cards = [
        ("Architecture", sd.get("architecture", "")),
        ("Tech Stack", sd.get("tech_stack", "")),
        ("Coordination", sd.get("coordination", "")),
        ("Security", sd.get("security", "")),
    ]
    lines.append('<div style="margin-top: 20px; display: grid; grid-template-columns: 1fr 1fr; gap: 16px;">')
    for card_title, card_text in cards:
        lines.append('  <div class="rec-card ani">')
        lines.append(f'    <h4>{_esc(card_title)}</h4>')
        lines.append(f'    <p>{_esc(card_text)}</p>')
        lines.append('  </div>')
    lines.append('</div>')

    # Agent roster
    if agents:
        lines.append('<h3 style="margin-top: 32px;" class="ani">Agent Roster</h3>')
        lines.append('<div class="roster-grid">')
        for agent in agents:
            name = _esc(agent.get("name", ""))
            icon = _esc(agent.get("icon", name[0] if name else "?"))
            color = agent.get("color", "accent")
            bg_var, text_var = _AGENT_COLORS.get(color, _AGENT_COLORS["accent"])
            desc = _esc(agent.get("description", ""))
            tools = agent.get("tools", [])

            lines.append('  <div class="roster-card ani">')
            lines.append(
                f'    <h4><span class="roster-icon" style="background:{bg_var};color:{text_var};">'
                f'{icon}</span> {name}</h4>'
            )
            lines.append(f'    <p>{desc}</p>')
            if tools:
                lines.append('    <div class="roster-tools">')
                for tool in tools:
                    lines.append(f'      <span class="tool-tag">{_esc(str(tool))}</span>')
                lines.append('    </div>')
            lines.append('  </div>')
        lines.append('</div>')

    return "\n".join(lines)


def _get_concept_definitions(pattern_ids: list[str]) -> dict[str, str]:
    """Fetch concept definitions from DB for use as tooltip fallback descriptions."""
    if not pattern_ids:
        return {}
    # Build lookup IDs: try both the canonical ID and the KG alias
    all_ids = set()
    for pid in pattern_ids:
        all_ids.add(pid)
        # Also try the KG alias (shorter ID) if one exists
        if pid in _PATTERN_ID_ALIASES:
            all_ids.add(_PATTERN_ID_ALIASES[pid])
    try:
        conn = get_connection()
        placeholders = ", ".join(["?"] * len(all_ids))
        rows = conn.execute(
            f"SELECT id, definition FROM concepts WHERE id IN ({placeholders}) AND definition IS NOT NULL",
            list(all_ids),
        ).fetchall()
        # Map back to canonical IDs
        result: dict[str, str] = {}
        for row_id, definition in rows:
            canonical = normalize_pattern_id(row_id)
            if definition:
                result[canonical] = definition
        return result
    except Exception:
        return {}


def _render_scorecard_rows(categories: dict, recommendation_narratives: dict | None) -> str:
    """Render <tr> rows for the scorecard table, grouped by category."""
    rec_narr = recommendation_narratives or {}

    # Collect all pattern IDs for tooltip lookup
    all_pids = []
    for cat in categories.values():
        for lv in cat.get("levels", {}).values():
            for p in lv.get("patterns", []):
                all_pids.append(p.get("pattern_id", ""))
    concept_defs = _get_concept_definitions(all_pids)

    rows = []

    for cat_key, cat in categories.items():
        rating = cat.get("rating", "not_started")
        rating_css = _RATING_CSS.get(rating, "rating-not-started")
        rating_label = _RATING_LABEL.get(rating, rating.title())

        # Category header row
        rows.append(f'<tr class="category-header">')
        rows.append(f'  <td colspan="4"><strong>{_esc(cat.get("name", cat_key))}</strong>')
        rows.append(f'    <span class="status-badge {rating_css}" style="margin-left:8px;">{_esc(rating_label)}</span>')
        rows.append(f'  </td>')
        rows.append('</tr>')

        for level_name in ("basic", "intermediate", "advanced"):
            level_data = cat.get("levels", {}).get(level_name, {})
            patterns = level_data.get("patterns", [])
            if not patterns:
                continue

            for p in patterns:
                pid = p.get("pattern_id", "")
                name = p.get("pattern_name", pid)
                status = p.get("status", "not_assessed")
                met = p.get("met", False)
                evidence = p.get("evidence", "")

                # Tooltip
                tooltip_text = rec_narr.get(pid) or evidence or concept_defs.get(pid, "")
                tooltip_detail = _esc(tooltip_text)
                book_ref = f"Ch. {cat.get('chapter', '')}"

                # Status badge
                status_css = _STATUS_CSS.get(status, "status-na")
                status_label = _STATUS_LABEL.get(status, status.title())

                # Indicator summary
                ind_summary = p.get("indicator_summary")
                ind_text = ""
                if ind_summary:
                    ind_text = f'{ind_summary["met"]}/{ind_summary["total"]}'

                rows.append("<tr>")
                rows.append(
                    f'  <td class="has-tooltip" data-tt-title="{_esc(name)}"'
                    f' data-tt-desc="{tooltip_detail}"'
                    f' data-tt-ref="{_esc(book_ref)}">'
                    f'<strong>{_esc(name)}</strong></td>'
                )
                rows.append(f'  <td class="level-cell">{_esc(level_name.title())}</td>')
                rows.append(f'  <td><span class="status-badge {status_css}">{status_label}</span></td>')
                evidence_display = _esc(evidence) if evidence else "&mdash;"
                ind_html = f' <span style="font-size:11px;color:var(--text-dim);">({ind_text})</span>' if ind_text else ""
                rows.append(f'  <td style="font-size:12px;color:var(--text-dim)">{evidence_display}{ind_html}</td>')
                rows.append("</tr>")

    return "\n".join(rows)


def _render_diagrams(
    diagram_current: str,
    diagram_target: str,
    tooltips_current: dict,
    tooltips_target: dict,
) -> str:
    """Render the stacked Mermaid diagram blocks with zoom controls and tooltip metadata."""
    lines = []
    lines.append('<div class="diagram-row">')

    for label, diagram, tt_id in [
        ("Current Architecture", diagram_current, "tooltips-current"),
        ("Target Architecture", diagram_target, "tooltips-target"),
    ]:
        lines.append(f'  <div class="mermaid-wrap ani" data-tooltips="{tt_id}">')
        lines.append('    <div class="zoom-controls">')
        lines.append('      <button onclick="zoomDiagram(this, 1.2)" title="Zoom in">+</button>')
        lines.append('      <button onclick="zoomDiagram(this, 0.8)" title="Zoom out">&minus;</button>')
        lines.append('      <button onclick="resetZoom(this)" title="Reset zoom">&#8634;</button>')
        lines.append('    </div>')
        lines.append(f'    <span class="mermaid-title">{_esc(label)}</span>')
        # Mermaid syntax is NOT html-escaped
        lines.append(f'    <pre class="mermaid">\n{diagram}\n    </pre>')
        lines.append('  </div>')

    lines.append('</div>')
    return "\n".join(lines)


def _render_tooltip_scripts(tooltips_current: dict, tooltips_target: dict) -> str:
    """Render the JSON script blocks for SVG node tooltip metadata."""
    lines = []
    lines.append('<script type="application/json" id="tooltips-current">')
    lines.append(json.dumps(tooltips_current, indent=2))
    lines.append('</script>')
    lines.append('')
    lines.append('<script type="application/json" id="tooltips-target">')
    lines.append(json.dumps(tooltips_target, indent=2))
    lines.append('</script>')
    return "\n".join(lines)


def _render_recommendations(roadmap: list[dict], recommendation_narratives: dict | None) -> str:
    """Render phased recommendation cards grouped by category."""
    rec_narr = recommendation_narratives or {}

    lines = []
    for phase in roadmap:
        phase_num = phase.get("phase", 1)
        cat_name = phase.get("category_name", "")
        current_rating = phase.get("current_rating", "")
        phase_css = _PHASE_CSS.get(phase_num, "phase-3")

        lines.append(f'<div class="rec-phase {phase_css} ani">')
        lines.append(f'  <div class="phase-header">Phase {phase_num}: {_esc(cat_name)}</div>')
        lines.append('  <div class="rec-cards">')

        for pattern in phase.get("patterns", []):
            pname = pattern.get("name", "")
            severity = pattern.get("severity", "")
            level = pattern.get("level", "")

            # Priority badge
            badge = ""
            if severity == "CRITICAL":
                badge = ' <span class="priority-badge priority-critical">Critical</span>'
            elif severity in ("WARNING", "HIGH"):
                badge = ' <span class="priority-badge priority-high">High</span>'

            # Description from Claude narratives
            desc = rec_narr.get(pname, "")

            # Missing indicators
            missing_inds = pattern.get("missing_indicators", [])
            if missing_inds and not desc:
                desc = "Missing: " + "; ".join(missing_inds[:3])

            lines.append('    <div class="rec-card">')
            lines.append(f'      <h4>{_esc(pname)}{badge}</h4>')
            lines.append(f'      <p style="font-size:12px;color:var(--text-dim);">{_esc(level.title())}</p>')
            lines.append(f'      <p>{_esc(desc)}</p>')
            lines.append('    </div>')

        lines.append('  </div>')
        lines.append('</div>')

    return "\n".join(lines)


def _render_failure_chain(failure_chain: dict) -> str:
    """Render the Ch. 7 five-step failure recovery chain."""
    steps = failure_chain.get("steps", [])
    coverage_pct = failure_chain.get("chain_coverage", "0%").rstrip("%")
    implemented = failure_chain.get("implemented", 0)
    total = failure_chain.get("total", 5)

    lines = []
    lines.append(f'<p class="subtitle">The recommended 5-step recovery chain. {implemented} of {total} steps covered.</p>')
    lines.append('')
    lines.append('<div style="display:flex;align-items:center;gap:16px;margin:20px 0;">')
    lines.append(f'  <div class="chain-coverage" data-count="{_esc(coverage_pct)}">{_esc(coverage_pct)}</div>')
    lines.append('  <div style="font-size:1.1rem;font-weight:700;">% Chain Coverage</div>')
    lines.append('</div>')
    lines.append('')
    lines.append('<div class="chain-steps ani">')

    for i, step in enumerate(steps):
        if i > 0:
            lines.append('  <div class="chain-arrow">&rarr;</div>')

        is_covered = not step.get("gap", True)
        css = "implemented" if is_covered else "missing"
        status_label = "Implemented" if is_covered else "Missing"
        step_num = step.get("step", i + 1)
        name = step.get("pattern_name", "")
        recovery = step.get("recovery", "")

        lines.append(f'  <div class="chain-step {css}">')
        lines.append(f'    <span class="step-num">Step {step_num}</span>')
        lines.append(f'    <span class="step-name">{_esc(name)}</span>')
        lines.append(f'    <span class="step-status">{status_label}</span>')
        lines.append(f'    <span style="font-size:11px;color:var(--text-dim)">{_esc(recovery)}</span>')
        lines.append('  </div>')

    lines.append('</div>')
    return "\n".join(lines)


def _render_stress_test(scenarios: list[dict]) -> str:
    """Render collapsible stress test scenarios."""
    lines = []
    lines.append('<p class="subtitle">Concrete scenarios illustrating how strengthening partial patterns protects the system.</p>')

    for scenario in scenarios:
        severity = scenario.get("severity", "INFO")
        title = scenario.get("title", "")
        sev_css = _SEVERITY_CSS.get(severity, "severity-info")
        cascade_steps = scenario.get("cascade_steps", [])
        book_ref = scenario.get("book_reference", {})
        chapter = book_ref.get("chapter", "")
        section = book_ref.get("section", "")
        recovery = scenario.get("recovery", "")
        inverted = scenario.get("inverted_pyramid")

        lines.append('')
        lines.append('<details class="scenario ani">')
        lines.append('  <summary>')
        lines.append(f'    <span class="severity-tag {sev_css}">{_esc(severity)}</span>')
        lines.append(f'    {_esc(title)}')
        lines.append('  </summary>')
        lines.append('  <div class="scenario-body">')

        for step in cascade_steps:
            step_num = step.get("step", 0)
            desc = step.get("description", "")
            code_ref = step.get("code_ref")
            lines.append('    <div class="cascade-step">')
            lines.append(f'      <span class="cascade-num">{step_num}</span>')
            ref_html = f' <span class="cascade-ref">{_esc(code_ref)}</span>' if code_ref else ""
            lines.append(f'      <div>{_esc(desc)}{ref_html}</div>')
            lines.append('    </div>')

        if recovery:
            lines.append(f'    <p style="margin-top:12px;font-size:0.85rem;"><strong>Recovery:</strong> {_esc(recovery)}</p>')

        if inverted:
            warning = inverted.get("warning", "")
            lines.append(f'    <p style="margin-top:8px;font-size:0.85rem;color:var(--amber);"><strong>Foundation dependency:</strong> {_esc(warning)}</p>')

        if chapter:
            lines.append(f'    <div class="book-ref">Ch. {_esc(str(chapter))} &mdash; {_esc(section)}</div>')

        lines.append('  </div>')
        lines.append('</details>')

    return "\n".join(lines)


def _render_footer(consultation_id: str, date: str) -> str:
    return (
        f'    Generated by <a href="https://github.com/anthropics/claude-code">Claude Code</a> '
        f'using <strong>iConsult</strong> MCP &mdash;\n'
        f'    Consultation ID: <code style="font-family:var(--font-mono);font-size:11px;">'
        f'{_esc(consultation_id)}</code><br>\n'
        f'    Reference: <em>Agentic Architectural Patterns for Building Multi-Agent Systems</em> '
        f'(Arsanjani &amp; Bustos, Packt 2026)'
    )


# ---------------------------------------------------------------------------
# Main tool
# ---------------------------------------------------------------------------

async def render_report(
    consultation_id: str,
    title: str,
    executive_brief: str,
    system_description: dict,
    agents: list[dict],
    diagram_current: str,
    diagram_target: str,
    tooltips_current: dict,
    tooltips_target: dict,
    recommendation_narratives: dict | None = None,
    output_dir: str | None = None,
) -> dict:
    """Render a complete HTML consultation report from template + data.

    Pulls structured data (scores, scenarios, coverage) from DuckDB internally.
    Claude only provides narrative content (~1700 tokens).

    Args:
        consultation_id: The consultation session to render.
        title: Report title (e.g. "MyProject Architecture Consultation").
        executive_brief: 3-4 sentence executive summary.
        system_description: Dict with keys: subtitle, architecture, tech_stack,
            coordination, security.
        agents: List of agent dicts: {name, icon, color, description, tools}.
        diagram_current: Raw Mermaid flowchart for current architecture.
        diagram_target: Raw Mermaid flowchart for target architecture.
        tooltips_current: SVG tooltip metadata {node_id: {title, desc, ref}}.
        tooltips_target: SVG tooltip metadata {node_id: {title, desc, ref}}.
        recommendation_narratives: Optional {pattern_id: description} for richer
            recommendation cards.
        output_dir: Output directory (default: ~/.agent/diagrams/).

    Returns:
        Dict with path to written HTML file and rendered sections list.
    """
    if not consultation_id or not consultation_id.strip():
        return {"error": "consultation_id is required"}

    # -----------------------------------------------------------------------
    # 1. Pull structured data from DB (deterministic, <1s each)
    # -----------------------------------------------------------------------
    score_data = await score_architecture(consultation_id)
    if "error" in score_data:
        return {"error": f"score_architecture failed: {score_data['error']}"}

    scenario_data = await generate_failure_scenarios(consultation_id)
    if "error" in scenario_data:
        return {"error": f"generate_failure_scenarios failed: {scenario_data['error']}"}

    coverage_data = await consultation_report(consultation_id)
    # coverage_data errors are non-fatal — used only for footer metadata

    # -----------------------------------------------------------------------
    # 2. Extract structured values
    # -----------------------------------------------------------------------
    categories = score_data.get("categories", {})
    roadmap = score_data.get("roadmap", [])
    scenarios = scenario_data.get("scenarios", [])
    failure_chain = scenario_data.get("failure_chain", {})

    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # -----------------------------------------------------------------------
    # 3. Load template
    # -----------------------------------------------------------------------
    if not os.path.exists(_TEMPLATE_FILE):
        return {"error": f"Template not found: {_TEMPLATE_FILE}"}

    with open(_TEMPLATE_FILE, "r", encoding="utf-8") as f:
        template = f.read()

    # -----------------------------------------------------------------------
    # 4. Build slot content
    # -----------------------------------------------------------------------
    slots: dict[str, str] = {
        "title": _esc(title),
        "hero": _render_hero(title, date),
        "exec_brief": _render_exec_brief(executive_brief),
        "maturity_banner": _render_maturity_banner(categories),
        "system_section": _render_system_section(system_description, agents),
        "scorecard_rows": _render_scorecard_rows(categories, recommendation_narratives),
        "diagrams": _render_diagrams(diagram_current, diagram_target, tooltips_current, tooltips_target),
        "recommendations": _render_recommendations(roadmap, recommendation_narratives),
        "failure_chain": _render_failure_chain(failure_chain),
        "stress_test": _render_stress_test(scenarios),
        "footer": _render_footer(consultation_id, date),
        "tooltip_scripts": _render_tooltip_scripts(tooltips_current, tooltips_target),
    }

    # -----------------------------------------------------------------------
    # 5. Replace slots
    # -----------------------------------------------------------------------
    output = template
    rendered_sections = []
    for slot_name, content in slots.items():
        marker = f"<!-- SLOT:{slot_name} -->"
        if marker in output:
            output = output.replace(marker, content)
            rendered_sections.append(slot_name)

    # -----------------------------------------------------------------------
    # 6. Write to disk
    # -----------------------------------------------------------------------
    if output_dir is None:
        output_dir = os.path.expanduser("~/.agent/diagrams")
    os.makedirs(output_dir, exist_ok=True)

    filename = f"consultation-{consultation_id}.html"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(output)

    return {
        "path": filepath,
        "sections": rendered_sections,
        "categories_rendered": len(categories),
        "scenarios_rendered": len(scenarios),
    }
