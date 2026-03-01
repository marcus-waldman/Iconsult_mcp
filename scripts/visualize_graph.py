"""
Visualize the knowledge graph with pyvis + interactive paranoia slider.

Usage:
    py scripts/visualize_graph.py                  # Default paranoia=5
    py scripts/visualize_graph.py --paranoia 3      # Start sparse
    py scripts/visualize_graph.py --no-open         # Don't auto-open browser
"""

import argparse
import json
import sys
import webbrowser
from pathlib import Path

_project_root = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, _project_root)
sys.path.insert(0, str(Path(_project_root) / "src"))

from pyvis.network import Network

from iconsult_mcp.db import get_connection

# -- Palette: 16 dark-mode-friendly chapter colors --
CHAPTER_COLORS = {
    1: "#FF6B6B",   # coral red
    2: "#4ECDC4",   # teal
    3: "#45B7D1",   # sky blue
    4: "#96CEB4",   # sage green
    5: "#FFEAA7",   # pale yellow
    6: "#DDA0DD",   # plum
    7: "#98D8C8",   # mint
    8: "#F7DC6F",   # gold
    9: "#BB8FCE",   # lavender
    10: "#85C1E9",  # light blue
    11: "#F0B27A",  # peach
    12: "#82E0AA",  # light green
    13: "#F1948A",  # salmon
    14: "#AED6F1",  # powder blue
    15: "#D7BDE2",  # light purple
    16: "#A3E4D7",  # light teal
}
FALLBACK_COLOR = "#888888"

# -- Edge colors by relationship type --
EDGE_COLORS = {
    "uses": "#7f8c8d",
    "extends": "#5dade2",
    "alternative_to": "#e74c3c",
    "component_of": "#2ecc71",
    "requires": "#f39c12",
    "conflicts_with": "#c0392b",
    "specializes": "#9b59b6",
    "precedes": "#1abc9c",
    "enables": "#3498db",
    "complements": "#27ae60",
}
FALLBACK_EDGE_COLOR = "#555555"


def paranoia_to_threshold(paranoia: int) -> float:
    """Convert paranoia (1-10) to confidence threshold."""
    return max(0.0, 1.0 - paranoia * 0.10)


def fetch_concepts(conn) -> list[dict]:
    """Fetch all concepts with their primary chapter number."""
    rows = conn.execute("""
        SELECT
            c.id, c.name, c.definition, c.category,
            (
                SELECT s.chapter_number
                FROM concept_sections cs
                JOIN sections s ON cs.section_id = s.id
                WHERE cs.concept_id = c.id
                ORDER BY cs.is_primary DESC, cs.confidence DESC
                LIMIT 1
            ) AS chapter_number
        FROM concepts c
        ORDER BY c.name
    """).fetchall()
    return [
        {
            "id": r[0],
            "name": r[1],
            "definition": r[2] if r[2] else "",
            "category": r[3] if r[3] else "uncategorized",
            "chapter": r[4],
        }
        for r in rows
    ]


def fetch_relationships(conn) -> list[dict]:
    """Fetch ALL relationships with concept names (slider filters client-side)."""
    rows = conn.execute("""
        SELECT
            r.from_concept_id, r.to_concept_id,
            r.relationship_type, r.confidence, r.description,
            cf.name AS from_name, ct.name AS to_name
        FROM relationships r
        JOIN concepts cf ON r.from_concept_id = cf.id
        JOIN concepts ct ON r.to_concept_id = ct.id
        ORDER BY r.confidence DESC
    """).fetchall()
    return [
        {
            "from": r[0],
            "to": r[1],
            "type": r[2],
            "confidence": r[3] if r[3] else 0.5,
            "description": r[4] if r[4] else "",
            "from_name": r[5],
            "to_name": r[6],
        }
        for r in rows
    ]


def build_network(
    concepts: list[dict],
    relationships: list[dict],
    initial_paranoia: int,
) -> tuple[Network, list[int]]:
    """Build a pyvis Network with all edges (slider hides them client-side)."""
    net = Network(
        height="100vh",
        width="100%",
        bgcolor="#1a1a2e",
        font_color="#e0e0e0",
        directed=True,
        select_menu=False,
        filter_menu=False,
    )

    concept_ids = {c["id"] for c in concepts}

    # Compute degree from ALL edges for stable node sizing
    degree = {}
    for rel in relationships:
        if rel["from"] in concept_ids:
            degree[rel["from"]] = degree.get(rel["from"], 0) + 1
        if rel["to"] in concept_ids:
            degree[rel["to"]] = degree.get(rel["to"], 0) + 1

    chapters_present = set()
    initial_threshold = paranoia_to_threshold(initial_paranoia)

    # Add nodes
    for c in concepts:
        ch = c["chapter"]
        color = CHAPTER_COLORS.get(ch, FALLBACK_COLOR)
        if ch is not None:
            chapters_present.add(ch)

        d = degree.get(c["id"], 0)
        size = 10 + d * 3

        ch_label = f"Ch. {ch}" if ch else "No chapter"
        defn = c["definition"][:300]
        if len(c["definition"]) > 300:
            defn += "..."
        tooltip = (
            f"<b>{c['name']}</b><br>"
            f"<i>{ch_label} &middot; {c['category']}</i><br><br>"
            f"{defn}"
        )

        net.add_node(
            c["id"],
            label=c["name"],
            title=tooltip,
            color=color,
            size=size,
            borderWidth=2,
            borderWidthSelected=4,
        )

    # Add ALL edges with confidence as custom property
    for i, rel in enumerate(relationships):
        if rel["from"] not in concept_ids or rel["to"] not in concept_ids:
            continue

        base_color = EDGE_COLORS.get(rel["type"], FALLBACK_EDGE_COLOR)
        width = 0.5 + rel["confidence"] * 3
        opacity = 0.3 + rel["confidence"] * 0.7
        alpha_hex = format(int(opacity * 255), "02x")
        edge_color = base_color + alpha_hex

        tooltip = (
            f"<b>{rel['type']}</b> (conf: {rel['confidence']:.2f})<br>"
            f"{rel['description'][:200]}"
        )

        # Start hidden if below initial threshold
        hidden = rel["confidence"] < initial_threshold

        net.add_edge(
            rel["from"],
            rel["to"],
            title=tooltip,
            color=edge_color,
            width=width,
            arrows="to",
            smooth={"type": "continuous"},
            confidence=rel["confidence"],
            relType=rel["type"],
            hidden=hidden,
        )

    # Physics & interaction options
    net.set_options("""
    {
        "physics": {
            "forceAtlas2Based": {
                "gravitationalConstant": -80,
                "centralGravity": 0.01,
                "springLength": 200,
                "springConstant": 0.02,
                "damping": 0.4,
                "avoidOverlap": 0.5
            },
            "solver": "forceAtlas2Based",
            "stabilization": {
                "enabled": true,
                "iterations": 300,
                "updateInterval": 25
            }
        },
        "interaction": {
            "hover": true,
            "tooltipDelay": 100,
            "navigationButtons": true,
            "keyboard": { "enabled": true },
            "zoomView": true,
            "dragView": true,
            "multiselect": true
        },
        "nodes": {
            "font": {
                "size": 12,
                "color": "#e0e0e0",
                "face": "Inter, Segoe UI, system-ui, sans-serif",
                "strokeWidth": 3,
                "strokeColor": "#1a1a2e"
            },
            "shape": "dot"
        },
        "edges": {
            "font": {
                "size": 10,
                "color": "#888888",
                "strokeWidth": 0,
                "align": "middle"
            },
            "arrows": {
                "to": { "enabled": true, "scaleFactor": 0.5 }
            }
        }
    }
    """)

    return net, sorted(chapters_present)


def inject_controls(
    html_path: Path,
    chapters: list[int],
    initial_paranoia: int,
    total_nodes: int,
    total_edges: int,
    concepts: list[dict],
    relationships: list[dict],
):
    """Inject slider, legend, sidebar, and all interactive JS into the HTML."""
    initial_threshold = paranoia_to_threshold(initial_paranoia)

    # Embed data as JSON for sidebar lookups
    concepts_json = json.dumps({c["id"]: c for c in concepts})
    rels_json = json.dumps(relationships)
    chapter_colors_json = json.dumps(CHAPTER_COLORS)
    edge_colors_json = json.dumps(EDGE_COLORS)

    # Build legend HTML with filter data attributes
    ch_items = "".join(
        f'<div class="leg-item" data-chapter="{ch}">'
        f'<span class="ch-dot" style="background:{CHAPTER_COLORS.get(ch, FALLBACK_COLOR)}"></span>'
        f'Ch. {ch}</div>'
        for ch in chapters
    )
    edge_items = "".join(
        f'<div class="leg-item" data-edgetype="{etype}">'
        f'<span class="edge-line" style="background:{color}"></span>'
        f'{etype}</div>'
        for etype, color in EDGE_COLORS.items()
    )

    controls_html = f"""
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ overflow: hidden; font-family: Inter, Segoe UI, system-ui, sans-serif; }}

        /* --- Bottom controls --- */
        #controls {{
            position: fixed; bottom: 0; left: 0; right: 0; z-index: 1000;
            background: rgba(26,26,46,0.95); border-top: 1px solid #333;
            padding: 12px 24px; display: flex; align-items: center; gap: 20px;
            font-size: 13px; color: #e0e0e0;
            backdrop-filter: blur(10px);
        }}
        #controls .label {{ font-weight: 700; color: #fff; white-space: nowrap; }}
        #controls .stat {{ color: #aaa; white-space: nowrap; }}
        #paranoia-slider {{
            -webkit-appearance: none; appearance: none;
            flex: 1; max-width: 360px; height: 6px;
            background: #333; border-radius: 3px; outline: none; cursor: pointer;
        }}
        #paranoia-slider::-webkit-slider-thumb {{
            -webkit-appearance: none; appearance: none;
            width: 20px; height: 20px; border-radius: 50%;
            background: #5dade2; border: 2px solid #fff;
            cursor: pointer; box-shadow: 0 0 6px rgba(93,173,226,0.5);
        }}
        #paranoia-slider::-moz-range-thumb {{
            width: 20px; height: 20px; border-radius: 50%;
            background: #5dade2; border: 2px solid #fff; cursor: pointer;
        }}
        #paranoia-value {{
            display: inline-block; min-width: 24px; text-align: center;
            font-weight: 700; font-size: 18px; color: #5dade2;
        }}

        /* --- Legend --- */
        #legend {{
            position: fixed; top: 12px; left: 12px; z-index: 1000;
            background: rgba(26,26,46,0.92); border: 1px solid #333;
            border-radius: 8px; padding: 14px 16px;
            font-size: 12px; color: #e0e0e0;
            max-height: calc(100vh - 80px); overflow-y: auto;
            backdrop-filter: blur(8px);
        }}
        #legend .title {{ font-size: 14px; font-weight: 700; color: #fff; margin-bottom: 8px; }}
        .leg-item {{
            display: flex; align-items: center; gap: 6px; margin: 2px 0;
            cursor: pointer; padding: 2px 4px; border-radius: 4px;
            transition: opacity 0.15s;
            user-select: none;
        }}
        .leg-item:hover {{ background: rgba(255,255,255,0.05); }}
        .leg-item.off {{ opacity: 0.25; }}
        .leg-item.off .ch-dot, .leg-item.off .edge-line {{ filter: grayscale(1); }}
        .ch-dot {{ display: inline-block; width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0; }}
        .edge-line {{ display: inline-block; width: 16px; height: 3px; border-radius: 1px; flex-shrink: 0; }}
        summary {{ cursor: pointer; font-weight: 600; margin-bottom: 4px; }}
        details {{ margin-top: 6px; }}
        .filter-actions {{
            display: flex; gap: 8px; margin: 4px 0 2px;
        }}
        .filter-btn {{
            background: none; border: 1px solid #333; border-radius: 4px;
            color: #888; font-size: 10px; padding: 1px 6px; cursor: pointer;
            font-family: inherit; transition: all 0.15s;
        }}
        .filter-btn:hover {{ color: #fff; border-color: #666; }}
        .hint {{ margin-top: 10px; color: #555; font-size: 10px; }}

        /* --- Search --- */
        #search-wrap {{ position: relative; margin-bottom: 10px; }}
        #search-input {{
            width: 100%; padding: 6px 10px 6px 28px;
            background: #1a1a2e; border: 1px solid #333; border-radius: 6px;
            color: #e0e0e0; font-size: 12px; outline: none;
            font-family: inherit;
        }}
        #search-input::placeholder {{ color: #555; }}
        #search-input:focus {{ border-color: #5dade2; }}
        #search-icon {{
            position: absolute; left: 9px; top: 50%; transform: translateY(-50%);
            color: #555; font-size: 12px; pointer-events: none;
        }}
        #search-results {{
            position: absolute; top: 100%; left: 0; right: 0;
            background: rgba(20,20,40,0.98); border: 1px solid #333;
            border-top: none; border-radius: 0 0 6px 6px;
            max-height: 260px; overflow-y: auto; display: none; z-index: 10;
        }}
        .search-item {{
            display: flex; align-items: center; gap: 8px;
            padding: 7px 10px; cursor: pointer; font-size: 12px;
        }}
        .search-item:hover, .search-item.active {{
            background: rgba(93,173,226,0.12);
        }}
        .search-item .ch-dot {{ width: 10px; height: 10px; }}
        .search-match {{ color: #5dade2; font-weight: 600; }}
        .search-no-match {{ color: #555; font-style: italic; padding: 8px 10px; font-size: 12px; }}

        /* --- Sidebar --- */
        #sidebar {{
            position: fixed; top: 0; right: -400px; width: 400px; height: 100vh;
            background: rgba(20,20,40,0.97); border-left: 1px solid #333;
            z-index: 1100; overflow-y: auto; padding: 0;
            transition: right 0.25s ease;
            backdrop-filter: blur(12px);
            font-size: 13px; color: #d0d0d0;
        }}
        #sidebar.open {{ right: 0; }}
        #sidebar-header {{
            position: sticky; top: 0; z-index: 1;
            background: rgba(20,20,40,0.98);
            padding: 16px 20px 12px; border-bottom: 1px solid #2a2a4a;
        }}
        #sidebar-close {{
            position: absolute; top: 12px; right: 16px;
            background: none; border: 1px solid #444; border-radius: 4px;
            color: #aaa; font-size: 18px; width: 28px; height: 28px;
            cursor: pointer; display: flex; align-items: center; justify-content: center;
            transition: all 0.15s;
        }}
        #sidebar-close:hover {{ background: #333; color: #fff; border-color: #666; }}
        #sidebar-title {{
            font-size: 17px; font-weight: 700; color: #fff;
            margin-right: 40px; line-height: 1.3;
        }}
        #sidebar-subtitle {{ font-size: 12px; color: #888; margin-top: 4px; }}
        #sidebar-body {{ padding: 16px 20px 80px; }}

        /* Sidebar components */
        .sb-section {{ margin-bottom: 18px; }}
        .sb-section-title {{
            font-size: 11px; font-weight: 700; text-transform: uppercase;
            letter-spacing: 0.08em; color: #666; margin-bottom: 8px;
        }}
        .sb-definition {{ color: #ccc; line-height: 1.55; }}
        .sb-badge {{
            display: inline-block; padding: 2px 10px; border-radius: 12px;
            font-size: 11px; font-weight: 600; margin-right: 6px; margin-bottom: 4px;
        }}
        .sb-conf-bar {{
            display: inline-block; height: 4px; border-radius: 2px;
            vertical-align: middle;
        }}
        .sb-conf-track {{
            display: inline-block; width: 60px; height: 4px; border-radius: 2px;
            background: #2a2a4a; vertical-align: middle; margin: 0 6px;
        }}
        .sb-rel-item {{
            display: flex; align-items: center; gap: 8px;
            padding: 6px 0; border-bottom: 1px solid #1e1e3a;
            font-size: 12px;
        }}
        .sb-rel-item:last-child {{ border-bottom: none; }}
        .sb-rel-arrow {{ color: #555; flex-shrink: 0; font-size: 14px; }}
        .sb-rel-name {{
            color: #aad; cursor: pointer; flex: 1; min-width: 0;
            overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
        }}
        .sb-rel-name:hover {{ color: #fff; text-decoration: underline; }}
        .sb-rel-type {{
            font-size: 10px; padding: 1px 6px; border-radius: 8px;
            white-space: nowrap; flex-shrink: 0;
        }}
        .sb-rel-conf {{ color: #777; font-size: 11px; flex-shrink: 0; width: 32px; text-align: right; }}
        .sb-edge-type {{
            font-size: 13px; font-weight: 600; padding: 3px 12px;
            border-radius: 12px; display: inline-block; margin-bottom: 4px;
        }}
        .sb-edge-conf {{
            display: flex; align-items: center; gap: 10px; margin: 12px 0;
        }}
        .sb-edge-conf-bar-track {{
            flex: 1; height: 6px; background: #2a2a4a; border-radius: 3px;
            overflow: hidden;
        }}
        .sb-edge-conf-bar-fill {{ height: 100%; border-radius: 3px; }}
        .sb-edge-conf-label {{ font-size: 20px; font-weight: 700; }}
        .sb-edge-endpoints {{ margin: 14px 0; }}
        .sb-edge-endpoint {{
            display: flex; align-items: center; gap: 8px; padding: 6px 0;
            cursor: pointer;
        }}
        .sb-edge-endpoint:hover .sb-rel-name {{ color: #fff; text-decoration: underline; }}
        .sb-edge-arrow {{ color: #5dade2; font-size: 16px; }}
        .sb-description {{ color: #bbb; line-height: 1.55; margin-top: 8px; }}
        .sb-empty {{ color: #555; font-style: italic; }}
    </style>

    <div id="legend">
        <div class="title">Iconsult Knowledge Graph</div>
        <div id="search-wrap">
            <span id="search-icon">&#128269;</span>
            <input type="text" id="search-input" placeholder="Search concepts..." autocomplete="off" spellcheck="false">
            <div id="search-results"></div>
        </div>
        <details open><summary>Chapters</summary>
            <div class="filter-actions">
                <button class="filter-btn" id="ch-all">All</button>
                <button class="filter-btn" id="ch-none">None</button>
            </div>
            {ch_items}
        </details>
        <details><summary>Edge types</summary>
            <div class="filter-actions">
                <button class="filter-btn" id="et-all">All</button>
                <button class="filter-btn" id="et-none">None</button>
            </div>
            {edge_items}
        </details>
        <div class="hint">Scroll to zoom &middot; Drag to pan &middot; Click to inspect</div>
    </div>

    <div id="sidebar">
        <div id="sidebar-header">
            <button id="sidebar-close">&times;</button>
            <div id="sidebar-title"></div>
            <div id="sidebar-subtitle"></div>
        </div>
        <div id="sidebar-body"></div>
    </div>

    <div id="controls">
        <span class="label">Paranoia</span>
        <span id="paranoia-value">{initial_paranoia}</span>
        <input type="range" id="paranoia-slider" min="1" max="10" value="{initial_paranoia}" step="1">
        <span class="stat">
            Threshold: &ge;<span id="threshold-value">{initial_threshold:.2f}</span>
        </span>
        <span class="stat">{total_nodes} concepts</span>
        <span class="stat"><span id="edge-count">-</span> / {total_edges} relationships</span>
    </div>

    <script>
    (function() {{
        var conceptsData = {concepts_json};
        var relsData = {rels_json};
        var chapterColors = {chapter_colors_json};
        var edgeColors = {edge_colors_json};
        var currentThreshold = {initial_threshold};

        var checkReady = setInterval(function() {{
            if (typeof edges === 'undefined' || typeof network === 'undefined') return;
            clearInterval(checkReady);
            init();
        }}, 100);

        // Shared references
        var showNodeSidebar;
        var focusActive = false;
        var originalNodeColors = {{}};
        var allEdges;

        // Filter state
        var activeChapters = {{}};   // chapter_number -> true/false
        var activeEdgeTypes = {{}};  // type_string -> true/false

        function init() {{
            // Capture original node colors for focus/restore
            var allNodes = nodes.get();
            for (var i = 0; i < allNodes.length; i++) {{
                originalNodeColors[allNodes[i].id] = {{
                    color: allNodes[i].color,
                    font: allNodes[i].font
                }};
            }}
            allEdges = edges.get();

            // Initialize all chapters and edge types as active
            for (var ch in chapterColors) {{ activeChapters[ch] = true; }}
            for (var et in edgeColors) {{ activeEdgeTypes[et] = true; }}

            initSlider();
            initFilters();
            initSidebar();
            initSearch();
        }}

        /* ---------- Unified refilter ---------- */
        function refilter() {{
            var edgeCountDisp = document.getElementById('edge-count');

            // Build set of chapters with nodes assigned
            var nodeChapter = {{}};
            for (var id in conceptsData) {{
                nodeChapter[id] = conceptsData[id].chapter;
            }}

            // Update node visibility based on chapter filter
            var nodeUpdates = [];
            var visibleNodes = {{}};
            for (var id in originalNodeColors) {{
                var ch = nodeChapter[id];
                var visible = ch == null || activeChapters[ch];
                visibleNodes[id] = visible;
                if (visible) {{
                    nodeUpdates.push({{
                        id: id,
                        color: originalNodeColors[id].color,
                        font: {{ color: '#e0e0e0', strokeWidth: 3, strokeColor: '#1a1a2e' }}
                    }});
                }} else {{
                    nodeUpdates.push({{
                        id: id,
                        color: {{ background: '#252540', border: '#252540' }},
                        font: {{ color: '#252540', strokeWidth: 0 }}
                    }});
                }}
            }}
            nodes.update(nodeUpdates);

            // Update edge visibility: confidence + edge type + both endpoints visible
            var visCount = 0;
            var edgeUpdates = [];
            for (var i = 0; i < allEdges.length; i++) {{
                var e = allEdges[i];
                var conf = e.confidence || 0;
                var typeOk = activeEdgeTypes[e.relType] !== false;
                var aboveThreshold = conf >= currentThreshold;
                var endpointsOk = visibleNodes[e.from] && visibleNodes[e.to];
                var show = aboveThreshold && typeOk && endpointsOk;
                if (show) visCount++;
                edgeUpdates.push({{ id: e.id, hidden: !show }});
            }}
            edges.update(edgeUpdates);
            edgeCountDisp.textContent = visCount;
        }}

        /* ---------- Focus mode ---------- */
        function focusOnNode(nodeId) {{
            focusActive = true;
            var neighborIds = {{}};
            neighborIds[nodeId] = true;
            for (var i = 0; i < relsData.length; i++) {{
                var r = relsData[i];
                if (r.confidence < currentThreshold) continue;
                if (!activeEdgeTypes[r.type]) continue;
                if (r.from === nodeId) neighborIds[r.to] = true;
                else if (r.to === nodeId) neighborIds[r.from] = true;
            }}

            var nodeUpdates = [];
            for (var id in originalNodeColors) {{
                if (neighborIds[id]) {{
                    nodeUpdates.push({{
                        id: id,
                        color: originalNodeColors[id].color,
                        font: {{ color: '#e0e0e0', strokeWidth: 3, strokeColor: '#1a1a2e' }}
                    }});
                }} else {{
                    nodeUpdates.push({{
                        id: id,
                        color: {{ background: '#252540', border: '#252540' }},
                        font: {{ color: '#353550', strokeWidth: 0 }}
                    }});
                }}
            }}
            nodes.update(nodeUpdates);

            var edgeUpdates = [];
            for (var i = 0; i < allEdges.length; i++) {{
                var e = allEdges[i];
                var connected = (e.from === nodeId || e.to === nodeId);
                var aboveThreshold = (e.confidence || 0) >= currentThreshold;
                var typeOk = activeEdgeTypes[e.relType] !== false;
                edgeUpdates.push({{ id: e.id, hidden: !(connected && aboveThreshold && typeOk) }});
            }}
            edges.update(edgeUpdates);
        }}

        function clearFocus() {{
            if (!focusActive) return;
            focusActive = false;
            refilter();
        }}

        /* ---------- Slider ---------- */
        function initSlider() {{
            var slider = document.getElementById('paranoia-slider');
            var paranoiaDisp = document.getElementById('paranoia-value');
            var thresholdDisp = document.getElementById('threshold-value');

            function applySlider(paranoia) {{
                currentThreshold = Math.max(0, 1.0 - paranoia * 0.1);
                paranoiaDisp.textContent = paranoia;
                thresholdDisp.textContent = currentThreshold.toFixed(2);
                if (focusActive) return; // focus mode manages its own edges
                refilter();
            }}

            applySlider(parseInt(slider.value));
            slider.addEventListener('input', function() {{
                applySlider(parseInt(this.value));
            }});
        }}

        /* ---------- Chapter & edge type filters ---------- */
        function initFilters() {{
            // Chapter toggles
            var chItems = document.querySelectorAll('.leg-item[data-chapter]');
            for (var i = 0; i < chItems.length; i++) {{
                chItems[i].addEventListener('click', function() {{
                    var ch = this.getAttribute('data-chapter');
                    activeChapters[ch] = !activeChapters[ch];
                    this.classList.toggle('off', !activeChapters[ch]);
                    clearFocus();
                    refilter();
                }});
            }}

            // Edge type toggles
            var etItems = document.querySelectorAll('.leg-item[data-edgetype]');
            for (var i = 0; i < etItems.length; i++) {{
                etItems[i].addEventListener('click', function() {{
                    var et = this.getAttribute('data-edgetype');
                    activeEdgeTypes[et] = !activeEdgeTypes[et];
                    this.classList.toggle('off', !activeEdgeTypes[et]);
                    clearFocus();
                    refilter();
                }});
            }}

            // All / None buttons
            document.getElementById('ch-all').addEventListener('click', function(e) {{
                e.stopPropagation();
                for (var ch in activeChapters) activeChapters[ch] = true;
                for (var i = 0; i < chItems.length; i++) chItems[i].classList.remove('off');
                clearFocus(); refilter();
            }});
            document.getElementById('ch-none').addEventListener('click', function(e) {{
                e.stopPropagation();
                for (var ch in activeChapters) activeChapters[ch] = false;
                for (var i = 0; i < chItems.length; i++) chItems[i].classList.add('off');
                clearFocus(); refilter();
            }});
            document.getElementById('et-all').addEventListener('click', function(e) {{
                e.stopPropagation();
                for (var et in activeEdgeTypes) activeEdgeTypes[et] = true;
                for (var i = 0; i < etItems.length; i++) etItems[i].classList.remove('off');
                clearFocus(); refilter();
            }});
            document.getElementById('et-none').addEventListener('click', function(e) {{
                e.stopPropagation();
                for (var et in activeEdgeTypes) activeEdgeTypes[et] = false;
                for (var i = 0; i < etItems.length; i++) etItems[i].classList.add('off');
                clearFocus(); refilter();
            }});
        }}

        /* ---------- Sidebar ---------- */
        function initSidebar() {{
            var sidebar = document.getElementById('sidebar');
            var sTitle = document.getElementById('sidebar-title');
            var sSub = document.getElementById('sidebar-subtitle');
            var sBody = document.getElementById('sidebar-body');
            var sClose = document.getElementById('sidebar-close');

            sClose.addEventListener('click', function() {{
                sidebar.classList.remove('open');
                network.unselectAll();
                clearFocus();
            }});

            // Click on canvas background to close
            network.on('click', function(params) {{
                if (params.nodes.length === 0 && params.edges.length === 0) {{
                    sidebar.classList.remove('open');
                    clearFocus();
                }}
            }});

            network.on('selectNode', function(params) {{
                if (params.nodes.length === 0) return;
                showNodeSidebar(params.nodes[0]);
            }});

            network.on('selectEdge', function(params) {{
                if (params.nodes.length > 0) return; // node click takes priority
                if (params.edges.length === 0) return;
                showEdgeSidebar(params.edges[0]);
            }});

            showNodeSidebar = function(nodeId) {{
                var c = conceptsData[nodeId];
                if (!c) return;
                var ch = c.chapter;
                var color = chapterColors[ch] || '#888';

                sTitle.textContent = c.name;
                sSub.innerHTML =
                    '<span class="sb-badge" style="background:' + color + '22;color:' + color + ';border:1px solid ' + color + '44">Ch. ' + (ch || '?') + '</span>' +
                    '<span class="sb-badge" style="background:#ffffff0a;color:#aaa;border:1px solid #333">' + c.category + '</span>';

                // Gather visible relationships for this node
                var outgoing = [], incoming = [];
                for (var i = 0; i < relsData.length; i++) {{
                    var r = relsData[i];
                    if (r.confidence < currentThreshold) continue;
                    if (r.from === nodeId) outgoing.push(r);
                    else if (r.to === nodeId) incoming.push(r);
                }}

                var html = '';

                // Definition
                if (c.definition) {{
                    html += '<div class="sb-section">' +
                        '<div class="sb-section-title">Definition</div>' +
                        '<div class="sb-definition">' + escHtml(c.definition) + '</div>' +
                        '</div>';
                }}

                // Outgoing
                html += '<div class="sb-section">' +
                    '<div class="sb-section-title">Outgoing (' + outgoing.length + ')</div>';
                if (outgoing.length === 0) {{
                    html += '<div class="sb-empty">No outgoing relationships at this threshold</div>';
                }} else {{
                    for (var i = 0; i < outgoing.length; i++) {{
                        html += renderRelItem(outgoing[i], 'out');
                    }}
                }}
                html += '</div>';

                // Incoming
                html += '<div class="sb-section">' +
                    '<div class="sb-section-title">Incoming (' + incoming.length + ')</div>';
                if (incoming.length === 0) {{
                    html += '<div class="sb-empty">No incoming relationships at this threshold</div>';
                }} else {{
                    for (var i = 0; i < incoming.length; i++) {{
                        html += renderRelItem(incoming[i], 'in');
                    }}
                }}
                html += '</div>';

                sBody.innerHTML = html;
                bindRelClicks();
                sidebar.classList.add('open');
            }}

            function showEdgeSidebar(edgeId) {{
                var e = edges.get(edgeId);
                if (!e) return;

                // Find the matching relationship data
                var rel = null;
                for (var i = 0; i < relsData.length; i++) {{
                    var r = relsData[i];
                    if (r.from === e.from && r.to === e.to) {{ rel = r; break; }}
                }}
                if (!rel) return;

                var typeColor = edgeColors[rel.type] || '#888';
                var conf = rel.confidence;

                sTitle.innerHTML = '';
                sSub.innerHTML =
                    '<span class="sb-edge-type" style="background:' + typeColor + '22;color:' + typeColor + ';border:1px solid ' + typeColor + '44">' + rel.type + '</span>';

                var html = '';

                // Confidence bar
                html += '<div class="sb-section">' +
                    '<div class="sb-section-title">Confidence</div>' +
                    '<div class="sb-edge-conf">' +
                    '<div class="sb-edge-conf-bar-track"><div class="sb-edge-conf-bar-fill" style="width:' + (conf * 100) + '%;background:' + typeColor + '"></div></div>' +
                    '<div class="sb-edge-conf-label" style="color:' + typeColor + '">' + conf.toFixed(2) + '</div>' +
                    '</div></div>';

                // Endpoints
                var fromC = conceptsData[rel.from];
                var toC = conceptsData[rel.to];
                var fromColor = chapterColors[fromC ? fromC.chapter : null] || '#888';
                var toColor = chapterColors[toC ? toC.chapter : null] || '#888';

                html += '<div class="sb-section">' +
                    '<div class="sb-section-title">Concepts</div>' +
                    '<div class="sb-edge-endpoints">' +
                    '<div class="sb-edge-endpoint" data-node="' + rel.from + '">' +
                    '<span class="ch-dot" style="background:' + fromColor + '"></span>' +
                    '<span class="sb-rel-name">' + escHtml(rel.from_name) + '</span>' +
                    '</div>' +
                    '<div style="text-align:center;color:#5dade2;font-size:18px;padding:2px 0">&#8595;</div>' +
                    '<div class="sb-edge-endpoint" data-node="' + rel.to + '">' +
                    '<span class="ch-dot" style="background:' + toColor + '"></span>' +
                    '<span class="sb-rel-name">' + escHtml(rel.to_name) + '</span>' +
                    '</div>' +
                    '</div></div>';

                // Description
                if (rel.description) {{
                    html += '<div class="sb-section">' +
                        '<div class="sb-section-title">Description</div>' +
                        '<div class="sb-description">' + escHtml(rel.description) + '</div>' +
                        '</div>';
                }}

                sBody.innerHTML = html;
                bindRelClicks();
                sidebar.classList.add('open');
            }}

            function renderRelItem(rel, direction) {{
                var typeColor = edgeColors[rel.type] || '#888';
                var arrow, targetId, targetName;
                if (direction === 'out') {{
                    arrow = '&#8594;';
                    targetId = rel.to;
                    targetName = rel.to_name;
                }} else {{
                    arrow = '&#8592;';
                    targetId = rel.from;
                    targetName = rel.from_name;
                }}
                var conf = rel.confidence;
                return '<div class="sb-rel-item">' +
                    '<span class="sb-rel-arrow">' + arrow + '</span>' +
                    '<span class="sb-rel-name" data-node="' + targetId + '">' + escHtml(targetName) + '</span>' +
                    '<span class="sb-rel-type" style="background:' + typeColor + '22;color:' + typeColor + '">' + rel.type + '</span>' +
                    '<span class="sb-rel-conf">' + conf.toFixed(2) + '</span>' +
                    '</div>';
            }}

            function bindRelClicks() {{
                var items = document.querySelectorAll('[data-node]');
                for (var i = 0; i < items.length; i++) {{
                    items[i].addEventListener('click', function() {{
                        var nid = this.getAttribute('data-node');
                        network.selectNodes([nid]);
                        network.focus(nid, {{ scale: 1.2, animation: {{ duration: 400 }} }});
                        if (focusActive) focusOnNode(nid);
                        showNodeSidebar(nid);
                    }});
                }}
            }}

            function escHtml(s) {{
                var d = document.createElement('div');
                d.textContent = s;
                return d.innerHTML;
            }}
        }}

        /* ---------- Search ---------- */
        function initSearch() {{
            var input = document.getElementById('search-input');
            var results = document.getElementById('search-results');
            var activeIdx = -1;
            var matches = [];

            // Build a sorted list of concepts for searching
            var conceptList = [];
            for (var id in conceptsData) {{
                conceptList.push({{ id: id, name: conceptsData[id].name, chapter: conceptsData[id].chapter }});
            }}
            conceptList.sort(function(a, b) {{ return a.name.localeCompare(b.name); }});

            input.addEventListener('input', function() {{
                var q = this.value.trim().toLowerCase();
                activeIdx = -1;
                if (q.length === 0) {{
                    results.style.display = 'none';
                    return;
                }}
                matches = [];
                for (var i = 0; i < conceptList.length && matches.length < 10; i++) {{
                    if (conceptList[i].name.toLowerCase().indexOf(q) !== -1) {{
                        matches.push(conceptList[i]);
                    }}
                }}
                renderResults(q);
            }});

            input.addEventListener('keydown', function(e) {{
                if (results.style.display === 'none') return;
                if (e.key === 'ArrowDown') {{
                    e.preventDefault();
                    activeIdx = Math.min(activeIdx + 1, matches.length - 1);
                    highlightActive();
                }} else if (e.key === 'ArrowUp') {{
                    e.preventDefault();
                    activeIdx = Math.max(activeIdx - 1, 0);
                    highlightActive();
                }} else if (e.key === 'Enter') {{
                    e.preventDefault();
                    if (activeIdx >= 0 && activeIdx < matches.length) {{
                        selectMatch(matches[activeIdx]);
                    }} else if (matches.length > 0) {{
                        selectMatch(matches[0]);
                    }}
                }} else if (e.key === 'Escape') {{
                    results.style.display = 'none';
                    input.blur();
                }}
            }});

            // Close dropdown on outside click
            document.addEventListener('click', function(e) {{
                if (!e.target.closest('#search-wrap')) {{
                    results.style.display = 'none';
                }}
            }});

            function renderResults(query) {{
                if (matches.length === 0) {{
                    results.innerHTML = '<div class="search-no-match">No matches</div>';
                    results.style.display = 'block';
                    return;
                }}
                var html = '';
                for (var i = 0; i < matches.length; i++) {{
                    var m = matches[i];
                    var color = chapterColors[m.chapter] || '#888';
                    // Highlight the matching substring
                    var name = m.name;
                    var idx = name.toLowerCase().indexOf(query);
                    var highlighted = escHtml(name.substring(0, idx)) +
                        '<span class="search-match">' + escHtml(name.substring(idx, idx + query.length)) + '</span>' +
                        escHtml(name.substring(idx + query.length));
                    html += '<div class="search-item" data-idx="' + i + '">' +
                        '<span class="ch-dot" style="background:' + color + '"></span>' +
                        '<span>' + highlighted + '</span></div>';
                }}
                results.innerHTML = html;
                results.style.display = 'block';

                // Bind clicks
                var items = results.querySelectorAll('.search-item');
                for (var i = 0; i < items.length; i++) {{
                    items[i].addEventListener('click', function() {{
                        var idx = parseInt(this.getAttribute('data-idx'));
                        selectMatch(matches[idx]);
                    }});
                }}
            }}

            function highlightActive() {{
                var items = results.querySelectorAll('.search-item');
                for (var i = 0; i < items.length; i++) {{
                    items[i].classList.toggle('active', i === activeIdx);
                }}
                if (activeIdx >= 0 && items[activeIdx]) {{
                    items[activeIdx].scrollIntoView({{ block: 'nearest' }});
                }}
            }}

            function selectMatch(m) {{
                network.selectNodes([m.id]);
                network.focus(m.id, {{ scale: 1.2, animation: {{ duration: 400 }} }});
                focusOnNode(m.id);
                showNodeSidebar(m.id);
                input.value = '';
                results.style.display = 'none';
            }}

            function escHtml(s) {{
                var d = document.createElement('div');
                d.textContent = s;
                return d.innerHTML;
            }}
        }}
    }})();
    </script>
    """

    html = html_path.read_text(encoding="utf-8")
    html = html.replace("</body>", f"{controls_html}\n</body>")
    html_path.write_text(html, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Visualize the Iconsult knowledge graph")
    parser.add_argument(
        "--paranoia", type=int, default=5, choices=range(1, 11),
        metavar="1-10",
        help="Initial paranoia level: 1=sparse ... 10=dense. Default: 5",
    )
    parser.add_argument(
        "--no-open", action="store_true",
        help="Don't auto-open the browser",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Output HTML path (default: data/graph.html)",
    )
    args = parser.parse_args()

    print(f"Initial paranoia: {args.paranoia}/10 (adjustable via slider)")

    conn = get_connection()
    concepts = fetch_concepts(conn)
    relationships = fetch_relationships(conn)
    print(f"Loaded {len(concepts)} concepts, {len(relationships)} relationships")

    if not concepts:
        print("No concepts found. Run the pipeline first.")
        sys.exit(1)

    net, chapters = build_network(concepts, relationships, args.paranoia)

    output_dir = Path(_project_root) / "data"
    output_dir.mkdir(exist_ok=True)
    output_path = Path(args.output) if args.output else Path(_project_root) / "knowledge-graph.html"

    net.save_graph(str(output_path))

    inject_controls(
        output_path,
        chapters,
        args.paranoia,
        total_nodes=len(concepts),
        total_edges=len(relationships),
        concepts=concepts,
        relationships=relationships,
    )

    print(f"Graph saved to {output_path}")

    if not args.no_open:
        webbrowser.open(output_path.as_uri())


if __name__ == "__main__":
    main()
