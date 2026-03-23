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
from iconsult_mcp.tools.rubric_data import normalize_pattern_id, _PATTERN_ID_ALIASES, _PATTERN_ID_ALIASES_REVERSE, RUBRIC
from iconsult_mcp.tools.failure_scenarios import generate_failure_scenarios
from iconsult_mcp.tools.consultation_report import consultation_report

# ---------------------------------------------------------------------------
# Template loading
# ---------------------------------------------------------------------------

_TEMPLATE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
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

_RATING_ICON: dict[str, str] = {
    "not_started": "&#x2014;",   # em dash
    "emerging": "&#x25B2;",      # upward triangle
    "established": "&#x2713;",   # check mark
    "mature": "&#x2605;",        # star
}


def _render_maturity_banner(categories: dict) -> str:
    lines = []
    lines.append('<div class="maturity-banner ani">')
    lines.append('  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;width:100%;">')

    for cat_key, cat in categories.items():
        rating = cat.get("rating", "not_started")
        css = _RATING_CSS.get(rating, "rating-not-started")
        label = _RATING_LABEL.get(rating, rating.title())
        icon = _RATING_ICON.get(rating, "")
        name = cat.get("name", cat_key)

        lines.append(f'    <div class="{css}" style="text-align:center;padding:14px 10px;border-radius:10px;border:1px solid var(--border);">')
        lines.append(f'      <div style="font-size:1.5rem;line-height:1;">{icon}</div>')
        lines.append(f'      <div style="font-weight:700;font-size:0.85rem;margin-top:6px;">{_esc(name)}</div>')
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
    # Build lookup IDs: try both the canonical ID and all known aliases
    # _PATTERN_ID_ALIASES maps kg_id → rubric_id; _REVERSE maps rubric_id → kg_id
    all_ids = set()
    for pid in pattern_ids:
        all_ids.add(pid)
        if pid in _PATTERN_ID_ALIASES:
            all_ids.add(_PATTERN_ID_ALIASES[pid])
        if pid in _PATTERN_ID_ALIASES_REVERSE:
            all_ids.add(_PATTERN_ID_ALIASES_REVERSE[pid])
        # Also check for common suffixes (_pattern)
        all_ids.add(pid + "_pattern")
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


def _get_rubric_description(pattern_id: str) -> str:
    """Build a fallback description from the rubric's indicator list."""
    for cat in RUBRIC.values():
        for lv in ("basic", "intermediate", "advanced"):
            for p in cat["levels"].get(lv, []):
                if p["id"] == pattern_id:
                    indicators = p.get("indicators", [])
                    if indicators:
                        return "Key capabilities: " + "; ".join(
                            ind.rstrip(".") for ind in indicators[:3]
                        ) + "."
    return ""


def _render_scorecard_rows(categories: dict, recommendation_narratives: dict | None) -> str:
    """Render separate scorecard tables per category."""
    rec_narr = recommendation_narratives or {}

    # Collect all pattern IDs for tooltip lookup
    all_pids = []
    for cat in categories.values():
        for lv in cat.get("levels", {}).values():
            for p in lv.get("patterns", []):
                all_pids.append(p.get("pattern_id", ""))
    concept_defs = _get_concept_definitions(all_pids)

    sections = []

    for cat_key, cat in categories.items():
        rating = cat.get("rating", "not_started")
        rating_css = _RATING_CSS.get(rating, "rating-not-started")
        rating_label = _RATING_LABEL.get(rating, rating.title())
        rating_icon = _RATING_ICON.get(rating, "")
        cat_name = cat.get("name", cat_key)

        # Check if category has any patterns
        has_patterns = any(
            lv.get("patterns")
            for lv in cat.get("levels", {}).values()
        )
        if not has_patterns:
            continue

        lines = []
        lines.append('<div class="cat-scorecard ani">')

        # Category header
        lines.append('  <div class="cat-scorecard-header">')
        lines.append(f'    <h3>{_esc(cat_name)}</h3>')
        lines.append(f'    <span class="status-badge {rating_css}">{rating_icon} {_esc(rating_label)}</span>')
        lines.append('  </div>')

        # Table
        lines.append('  <div class="cat-scorecard-body">')
        lines.append('  <table class="scorecard-table">')
        lines.append('  <thead><tr>')
        lines.append('    <th>Pattern</th>')
        lines.append('    <th style="text-align:center;">Level</th>')
        lines.append('    <th>Status</th>')
        lines.append('  </tr></thead>')
        lines.append('  <tbody>')

        for level_name in ("basic", "intermediate", "advanced"):
            level_data = cat.get("levels", {}).get(level_name, {})
            patterns = level_data.get("patterns", [])
            if not patterns:
                continue

            for p in patterns:
                pid = p.get("pattern_id", "")
                name = p.get("pattern_name", pid)
                status = p.get("status", "not_assessed")
                evidence = p.get("evidence", "")

                # Build tooltip from evidence / narratives / concept defs
                tooltip_text = rec_narr.get(pid) or evidence or concept_defs.get(pid, "")
                tooltip_detail = _esc(tooltip_text)
                book_ref = f"Ch. {cat.get('chapter', '')}"

                # Status badge with tooltip on hover
                status_css = _STATUS_CSS.get(status, "status-na")
                status_label = _STATUS_LABEL.get(status, status.title())

                # Indicator summary appended to status
                ind_summary = p.get("indicator_summary")
                ind_text = ""
                if ind_summary:
                    ind_text = f' ({ind_summary["met"]}/{ind_summary["total"]})'

                lines.append('  <tr>')
                lines.append(
                    f'    <td class="has-tooltip" data-tt-title="{_esc(name)}"'
                    f' data-tt-desc="{tooltip_detail}"'
                    f' data-tt-ref="{_esc(book_ref)}">'
                    f'<strong>{_esc(name)}</strong></td>'
                )
                lines.append(f'    <td class="level-cell">{_esc(level_name.title())}</td>')
                # Status badge — evidence shown via tooltip on hover
                lines.append(
                    f'    <td><span class="status-badge {status_css} has-tooltip"'
                    f' data-tt-title="{_esc(name)}: {status_label}"'
                    f' data-tt-desc="{tooltip_detail}"'
                    f' data-tt-ref="{_esc(book_ref)}"'
                    f'>{status_label}{_esc(ind_text)}</span></td>'
                )
                lines.append('  </tr>')

        lines.append('  </tbody></table>')
        lines.append('  </div>')
        lines.append('</div>')
        sections.append("\n".join(lines))

    return "\n".join(sections)


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
        lines.append('      <button onclick="openDiagramWindow(this)" title="Open in new window">&#x29C9;</button>')
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


def _match_node_to_pattern(
    node_id: str,
    title: str,
    pattern_lookup: dict[str, dict],
) -> dict | None:
    """Best-effort fuzzy match of a tooltip node to a pattern assessment.

    Returns the matched pattern dict or None.  Priority:
    1. Exact node_id match against pattern_id
    2. Title contains pattern_name (or vice versa)
    3. >50% word overlap
    """
    # Normalize for comparison
    nid = node_id.lower().replace(" ", "_").replace("-", "_")
    title_lower = title.lower()
    title_words = set(title_lower.split())

    # 1. Exact ID match
    if nid in pattern_lookup:
        return pattern_lookup[nid]

    # 2/3. Score all patterns by name similarity
    best, best_score = None, 0.0
    for _pid, pdata in pattern_lookup.items():
        pname = pdata.get("pattern_name", "").lower()
        pwords = set(pname.split())

        # Containment checks (strong signal)
        if pname and (pname in title_lower or title_lower in pname):
            score = 0.9
        elif pwords and title_words:
            overlap = len(title_words & pwords)
            union = len(title_words | pwords)
            score = overlap / union if union else 0.0
        else:
            score = 0.0

        if score > best_score:
            best_score = score
            best = pdata

    return best if best_score > 0.4 else None


# Max indicators shown in tooltip before "+N more"
_MAX_TOOLTIP_INDICATORS = 4


def _enrich_tooltips(
    tooltips: dict,
    categories: dict,
    scenarios: list[dict],
) -> dict:
    """Auto-enrich tooltip entries with pattern status, indicators, and failure teasers.

    Cross-references tooltip node IDs/titles against scored pattern data
    and failure scenarios.  Unmatched nodes pass through unchanged.
    """
    if not tooltips:
        return tooltips

    # Build flat lookup: pattern_id → {pattern_name, status, indicator_summary, indicators_raw}
    pattern_lookup: dict[str, dict] = {}
    for _cat_key, cat in categories.items():
        for _lv, lv_data in cat.get("levels", {}).items():
            for p in lv_data.get("patterns", []):
                pid = p["pattern_id"]
                entry = {
                    "pattern_id": pid,
                    "pattern_name": p.get("pattern_name", ""),
                    "status": p.get("status", "not_assessed"),
                    "indicator_summary": p.get("indicator_summary"),
                }
                pattern_lookup[pid] = entry
                # Also key by slugified name for fuzzy matching
                slug = p.get("pattern_name", "").lower().replace(" ", "_").replace("-", "_")
                if slug and slug not in pattern_lookup:
                    pattern_lookup[slug] = entry

    # Build scenario lookup: pattern_id → trigger text
    scenario_lookup: dict[str, str] = {}
    for s in scenarios:
        mp = s.get("missing_pattern", {})
        spid = mp.get("id", "")
        if spid and "trigger" in s:
            scenario_lookup[spid] = s["trigger"]

    # Get raw indicator data from rubric for matched patterns
    from iconsult_mcp.tools.rubric_data import get_pattern_indicators as _get_indicators
    from iconsult_mcp.db import get_consultation

    enriched = {}
    for node_id, meta in tooltips.items():
        meta = dict(meta)  # shallow copy
        title = meta.get("title", node_id)

        match = _match_node_to_pattern(node_id, title, pattern_lookup)
        if match:
            status = match["status"]
            pid = match["pattern_id"]

            # Only add status for assessed patterns
            if status not in ("not_assessed",):
                meta["status"] = status

            # Indicators: fetch from rubric, cross-ref with summary
            ind_summary = match.get("indicator_summary")
            if ind_summary and status not in ("not_assessed", "not_applicable"):
                rubric_inds = _get_indicators(pid)
                if rubric_inds:
                    # We only have summary counts, not per-indicator met/unmet
                    # from score_data.  Build a display list from rubric text.
                    # For implemented patterns with all met, skip indicators.
                    if status == "implemented" and ind_summary.get("not_met", 0) == 0:
                        pass  # All good — don't clutter
                    else:
                        meta["indicators"] = rubric_inds
                        meta["indicators_met"] = ind_summary.get("met", 0)
                        meta["indicators_total"] = ind_summary.get("met", 0) + ind_summary.get("not_met", 0)

            # Failure teaser: only for missing/partial
            if status in ("missing", "partial") and pid in scenario_lookup:
                meta["failure_teaser"] = scenario_lookup[pid]

        enriched[node_id] = meta

    return enriched


def _render_recommendations(
    roadmap: list[dict],
    recommendation_narratives: dict | None,
    concept_defs: dict[str, str] | None = None,
) -> str:
    """Render phased recommendation cards grouped by category.

    Each card includes: what the pattern is (concept def), why it matters
    (missing indicators / narrative), and where to start (book ref).
    """
    rec_narr = recommendation_narratives or {}
    cdefs = concept_defs or {}

    lines = []
    for phase in roadmap:
        phase_num = phase.get("phase", 1)
        cat_name = phase.get("category_name", "")
        current_rating = phase.get("current_rating", "")
        phase_css = _PHASE_CSS.get(min(phase_num, 3), "phase-3")
        rating_css = _RATING_CSS.get(current_rating, "rating-not-started")
        rating_label = _RATING_LABEL.get(current_rating, current_rating)

        lines.append(f'<div class="rec-phase {phase_css} ani">')
        lines.append(
            f'  <div class="phase-header">Phase {phase_num}: {_esc(cat_name)}'
            f'  <span class="status-badge {rating_css}" style="margin-left:8px;font-size:11px;">'
            f'Currently {_esc(rating_label)}</span></div>'
        )
        lines.append('  <div class="rec-cards">')

        for pattern in phase.get("patterns", []):
            pname = pattern.get("name", "")
            severity = pattern.get("severity", "")
            level = pattern.get("level", "")
            status = pattern.get("status", "missing")
            missing_inds = pattern.get("missing_indicators", [])

            # Priority badge
            badge = ""
            if severity == "CRITICAL":
                badge = ' <span class="priority-badge priority-critical">Critical</span>'
            elif severity in ("WARNING", "HIGH"):
                badge = ' <span class="priority-badge priority-high">High</span>'

            # What is this pattern? (narrative > concept def > rubric indicators)
            pattern_id = pattern.get("pattern_id", "")
            what_text = (
                rec_narr.get(pattern_id)
                or rec_narr.get(pname)
                or cdefs.get(pattern_id, "")
                or _get_rubric_description(pattern_id)
            )

            # Why is it needed? (missing indicators)
            why_items = []
            if missing_inds:
                for ind in missing_inds[:4]:
                    why_items.append(f'<li>{_esc(ind)}</li>')

            lines.append('    <div class="rec-card">')
            lines.append(f'      <h4>{_esc(pname)}{badge}</h4>')
            lines.append(f'      <div style="font-size:12px;color:var(--text-dim);margin-bottom:6px;">{_esc(level.title())} pattern</div>')

            if what_text:
                lines.append(f'      <p>{_esc(what_text)}</p>')

            if why_items:
                lines.append('      <div style="margin-top:8px;">')
                lines.append('        <div style="font-size:12px;font-weight:600;color:var(--text-dim);margin-bottom:4px;">Indicators to address:</div>')
                lines.append(f'        <ul style="margin:0;padding-left:18px;font-size:0.85rem;">{"".join(why_items)}</ul>')
                lines.append('      </div>')

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

    # Fetch concept definitions for recommendation cards
    gap_pids = [g["pattern_id"] for phase in roadmap for g in phase.get("patterns", [])]
    concept_defs = _get_concept_definitions(gap_pids)

    # Enrich tooltips with pattern status, indicators, failure teasers
    enriched_current = _enrich_tooltips(tooltips_current, categories, scenarios)
    enriched_target = _enrich_tooltips(tooltips_target, categories, scenarios)

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
        "recommendations": _render_recommendations(roadmap, recommendation_narratives, concept_defs),
        "failure_chain": _render_failure_chain(failure_chain),
        "stress_test": _render_stress_test(scenarios),
        "footer": _render_footer(consultation_id, date),
        "tooltip_scripts": _render_tooltip_scripts(enriched_current, enriched_target),
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
