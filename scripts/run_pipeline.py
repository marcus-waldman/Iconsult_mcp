"""
Pipeline orchestrator — runs all phases in order.

Usage:
    py scripts/run_pipeline.py              # Run all phases
    py scripts/run_pipeline.py --phase 1a   # Run only phase 1a
    py scripts/run_pipeline.py --phase 3c 3d 3e  # Run specific Phase 3 sub-phases
    py scripts/run_pipeline.py --phase 3 4  # Run all Phase 3 sub-phases then Phase 4
    py scripts/run_pipeline.py --reset      # Clear all pipeline metadata and re-run
"""

import argparse
import asyncio
import sys
from pathlib import Path

_project_root = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, _project_root)
sys.path.insert(0, str(Path(_project_root) / "src"))

# Phase 3 sub-phases that can be run individually
PHASE3_SUBS = {"3a", "3b", "3c", "3d", "3e"}
ALL_PHASES = {"1a", "1b", "2", "3", "4"} | PHASE3_SUBS


def reset_pipeline():
    """Clear all pipeline metadata to force re-running all phases."""
    from iconsult_mcp.db import get_connection
    conn = get_connection()
    conn.execute("DELETE FROM pipeline_metadata")
    print("Pipeline metadata cleared. All phases will re-run.")


def _resolve_phases(phases: list[str] | None) -> list[str]:
    """Resolve phase arguments into an ordered list of phases to run.

    - "3" expands to ["3a", "3b", "3c", "3d", "3e"]
    - Sub-phases like "3c" are kept as-is
    - Order is preserved: 1a, 1b, 2, 3a-3e, 4
    """
    canonical_order = ["1a", "1b", "2", "3a", "3b", "3c", "3d", "3e", "4"]

    if phases is None:
        return canonical_order

    expanded = []
    for p in phases:
        if p == "3":
            expanded.extend(["3a", "3b", "3c", "3d", "3e"])
        elif p in ALL_PHASES:
            expanded.append(p)
        else:
            print(f"Unknown phase: {p}. Valid: 1a, 1b, 2, 3, 3a, 3b, 3c, 3d, 3e, 4")
            sys.exit(1)

    # Deduplicate while preserving canonical order
    seen = set()
    ordered = []
    for p in canonical_order:
        if p in expanded and p not in seen:
            ordered.append(p)
            seen.add(p)
    return ordered


async def run_all(phases: list[str] | None = None):
    """Run all (or specified) pipeline phases."""

    to_run = _resolve_phases(phases)
    phase3_subs = [p for p in to_run if p in PHASE3_SUBS]
    top_level = [p for p in to_run if p not in PHASE3_SUBS]

    if "1a" in top_level:
        print("\n" + "=" * 60)
        print("PHASE 1a: Parsing index -> concepts")
        print("=" * 60)
        from scripts.parse_index import main as run_1a
        run_1a()

    if "1b" in top_level:
        print("\n" + "=" * 60)
        print("PHASE 1b: Parsing book -> sections")
        print("=" * 60)
        from scripts.parse_book import main as run_1b
        run_1b()

    if "2" in top_level:
        print("\n" + "=" * 60)
        print("PHASE 2: Tagging concepts to sections")
        print("=" * 60)
        from scripts.tag_concepts import run_phase2
        await run_phase2()

    if phase3_subs:
        sub_labels = ", ".join(phase3_subs)
        print("\n" + "=" * 60)
        print(f"PHASE 3: Discovering relationships (sub-phases: {sub_labels})")
        print("=" * 60)
        from scripts.discover_relationships import run_phase3
        await run_phase3(sub_phases=phase3_subs)

    if "4" in top_level:
        print("\n" + "=" * 60)
        print("PHASE 4: Building final graph")
        print("=" * 60)
        from scripts.build_graph import run_phase4
        await run_phase4()

    print("\n" + "=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)

    from iconsult_mcp.db import get_stats
    stats = get_stats()
    print(f"\nFinal graph: {stats['concepts']} concepts, "
          f"{stats['sections']} sections, "
          f"{stats['relationships']} relationships")


def main():
    parser = argparse.ArgumentParser(description="Run the iconsult knowledge graph pipeline")
    parser.add_argument("--phase", nargs="+", help="Run specific phases (1a, 1b, 2, 3, 3a-3e, 4)")
    parser.add_argument("--reset", action="store_true", help="Clear pipeline metadata before running")
    args = parser.parse_args()

    if args.reset:
        reset_pipeline()

    asyncio.run(run_all(args.phase))


if __name__ == "__main__":
    main()
