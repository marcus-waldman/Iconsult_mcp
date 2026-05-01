"""Phase 5c visual smoke test — render a multi-book consultation report.

Drives the live arsanjani+gulli demo consultation produced by
`verify_phase4e.py` through `render_report` and writes the HTML to
~/.agent/diagrams/. Open the file in a browser and eyeball:

  1. Scorecard rows for assessed patterns carry [arsanjani_2026] /
     [gulli_2025] tags next to the pattern name (subtle gray monospace).
  2. Stress test scenarios carry the same style of badge next to the
     title.
  3. Unassessed patterns and rubric ratings are unchanged — the badges
     should not crowd the existing UI.

Re-run after `verify_phase4e.py`. The consultation_id changes per run
(timestamped); pass it explicitly via the CLI arg to render that one,
or omit and the script reuses the latest consultation row tied to the
demo project.
"""

from __future__ import annotations

import asyncio
import os
import sys

from iconsult_mcp.db import get_connection
from iconsult_mcp.tools.render_report import render_report


# Mock narrative — Claude would normally supply this; for the smoke test
# we just need plausible HTML so badges have somewhere to live.
NARRATIVES = {
    "title": "Phase 5 Provenance Smoke Test — arsanjani + gulli",
    "executive_brief": (
        "This demo report exercises Phase 5 multi-book provenance: assessments "
        "logged against both arsanjani_2026 and gulli_2025 should surface as "
        "<strong>book-badge</strong> tags next to pattern names in the scorecard "
        "and next to scenario titles in the stress test."
    ),
    "system_description": {
        "subtitle": "Cross-book canonical layer demo",
        "architecture": "Demo project with triaged arsanjani + gulli, KG built",
        "tech_stack": "DuckDB + canonical_concepts + project-scoped routing",
        "coordination": "Supervisor architecture (arsanjani) + agent-to-agent delegation (gulli)",
        "security": "Out of scope for this smoke test",
    },
    "agents": [
        {
            "name": "Manager",
            "icon": "M",
            "color": "accent",
            "description": "Orchestrates sub-agents; representative of supervisor_architecture",
            "tools": ["delegate_task", "assess_outcome"],
        },
    ],
    "diagram_current": (
        "flowchart TD\n"
        "  MGR[Manager] --> WORKER[Worker]\n"
        "  classDef existing fill:#0d948822,stroke:#0d9488\n"
        "  class MGR,WORKER existing"
    ),
    "diagram_target": (
        "flowchart TD\n"
        "  MGR[Manager] --> WORKER[Worker]\n"
        "  MGR --> HEAL[Auto-Healing]\n"
        "  classDef existing fill:#0d948822,stroke:#0d9488\n"
        "  classDef newcap fill:#d9770622,stroke:#d97706,stroke-dasharray:5 5\n"
        "  class MGR,WORKER existing\n"
        "  class HEAL newcap"
    ),
    "tooltips_current": {
        "MGR": {"title": "Manager", "desc": "Supervisor pattern from arsanjani Ch. 5", "ref": "manager.py"},
        "WORKER": {"title": "Worker", "desc": "Delegated worker (gulli)", "ref": "worker.py"},
    },
    "tooltips_target": {
        "MGR": {"title": "Manager", "desc": "Supervisor pattern, hardened", "ref": "manager.py"},
        "WORKER": {"title": "Worker", "desc": "Delegated worker", "ref": "worker.py"},
        "HEAL": {"title": "Auto-Healing", "desc": "NEW: Crash recovery", "ref": "Ch. 7"},
    },
}


def _latest_consultation_for_project(project_id: str) -> str | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM consultations WHERE project_id = ? "
        "ORDER BY created_at DESC LIMIT 1",
        [project_id],
    ).fetchone()
    return row[0] if row else None


async def main() -> int:
    if len(sys.argv) > 1:
        cid = sys.argv[1]
        print(f"Rendering with explicit consultation_id={cid}")
    else:
        cid = _latest_consultation_for_project("proj_eed395e3a026")
        if not cid:
            print(
                "ERROR: no consultation found for proj_eed395e3a026.\n"
                "Run scripts/verify_phase4e.py first.",
                file=sys.stderr,
            )
            return 1
        print(f"Rendering latest consultation for proj_eed395e3a026: {cid}")

    out_dir = os.path.expanduser("~/.agent/diagrams")
    result = await render_report(
        consultation_id=cid,
        output_dir=out_dir,
        **NARRATIVES,
    )

    if "error" in result:
        print(f"ERROR: {result['error']}", file=sys.stderr)
        return 1

    print()
    print("=" * 72)
    print("Render complete.")
    print("=" * 72)
    print(f"path     : {result['path']}")
    print(f"sections : {len(result['sections'])} rendered")
    print(f"categories rendered : {result['categories_rendered']}")
    print(f"scenarios rendered  : {result['scenarios_rendered']}")
    print()
    print("Open the file in a browser and verify:")
    print("  1. Scorecard rows for supervisor_architecture and "
          "agent_delegates_to_agent show [arsanjani_2026] / [gulli_2025] "
          "tags next to the pattern name (subtle gray monospace).")
    print("  2. Stress test scenarios carry the same badge next to the title.")
    print("  3. Unassessed patterns have no badge — only entries with "
          "source_book_id should be tagged.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
