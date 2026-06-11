"""
Pipeline orchestrator — runs all phases in order for a single book.

Usage:
    py scripts/run_pipeline.py                          # Run all phases for arsanjani_2026
    py scripts/run_pipeline.py --book hohpe_eip_2003    # Run all phases for another book
    py scripts/run_pipeline.py --phase 1a               # Run only phase 1a
    py scripts/run_pipeline.py --phase 3c 3d 3e         # Run specific Phase 3 sub-phases
    py scripts/run_pipeline.py --reset                  # Clear THIS book's pipeline metadata first
"""

import argparse
import asyncio
import sys
from pathlib import Path

_project_root = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, _project_root)
sys.path.insert(0, str(Path(_project_root) / "src"))

DEFAULT_BOOK_ID = "arsanjani_2026"

PHASE3_SUBS = {"3a", "3b", "3c", "3d", "3e"}
ALL_PHASES = {"1a", "1b", "2", "3", "4"} | PHASE3_SUBS


def reset_pipeline(book_id: str):
    """Clear pipeline metadata for one book so its phases re-run."""
    from iconsult_mcp.db import get_connection
    conn = get_connection()
    # Per-book keys are suffixed `:{book_id}`. Legacy unsuffixed keys are
    # cleared too, since they're no longer written by the parameterized
    # scripts and can otherwise cause confusing skip-decisions.
    conn.execute(
        "DELETE FROM pipeline_metadata WHERE key LIKE ? OR key NOT LIKE '%:%'",
        [f"%:{book_id}"],
    )
    print(f"Pipeline metadata cleared for {book_id}. All phases will re-run.")


def _resolve_phases(phases: list[str] | None) -> list[str]:
    """Resolve phase arguments into an ordered list of phases to run."""
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

    seen = set()
    ordered = []
    for p in canonical_order:
        if p in expanded and p not in seen:
            ordered.append(p)
            seen.add(p)
    return ordered


def _ensure_book_registered(book_id: str):
    """Verify that the requested book exists in config.BOOKS and the books table."""
    from iconsult_mcp.config import BOOKS, list_registered_books
    from iconsult_mcp.db import get_book

    if book_id not in BOOKS:
        print(
            f"ERROR: Unknown book_id '{book_id}'. "
            f"Registered in config.BOOKS: {list_registered_books()}"
        )
        sys.exit(1)
    if get_book(book_id) is None:
        print(
            f"ERROR: Book '{book_id}' is registered in config.BOOKS but absent from "
            "the books table. Run scripts/seed_books_table.py first."
        )
        sys.exit(1)


async def run_all(book_id: str, phases: list[str] | None = None):
    """Run all (or specified) pipeline phases for one book."""
    _ensure_book_registered(book_id)

    to_run = _resolve_phases(phases)
    phase3_subs = [p for p in to_run if p in PHASE3_SUBS]
    top_level = [p for p in to_run if p not in PHASE3_SUBS]

    # The phase scripts read `--book` from sys.argv, so set it for direct calls.
    # We invoke their internal entry-points (run_phaseN / main()) instead of
    # subprocess to keep state in-process, so we pass book_id directly.

    if "1a" in top_level:
        print("\n" + "=" * 60)
        print(f"PHASE 1a: Parsing index -> concepts ({book_id})")
        print("=" * 60)
        # parse_index has no async run_phase, but main() reads argv. We invoke
        # its functions directly to bypass argv parsing.
        from scripts.parse_index import insert_concepts, parse_index
        from iconsult_mcp.config import get_book_paths
        index_path = get_book_paths(book_id)["index"]
        if not index_path.exists():
            print(f"ERROR: Index file not found: {index_path}")
            sys.exit(1)
        concepts = parse_index(index_path, book_id)
        print(f"Found {len(concepts)} concepts")
        insert_concepts(concepts, book_id, index_path)

    if "1b" in top_level:
        print("\n" + "=" * 60)
        print(f"PHASE 1b: Parsing book -> sections ({book_id})")
        print("=" * 60)
        from scripts.parse_book import (
            insert_sections,
            load_boundaries_from_db,
            parse_book,
        )
        from iconsult_mcp.config import get_book_paths
        if not load_boundaries_from_db(book_id) and book_id != DEFAULT_BOOK_ID:
            print(
                f"ERROR: No chapter_boundaries in books table for '{book_id}'. "
                "Run scripts/seed_books_table.py first."
            )
            sys.exit(1)
        book_path = get_book_paths(book_id)["book"]
        sections = parse_book(book_path, book_id)
        print(f"Found {len(sections)} sections")
        insert_sections(sections, book_id, book_path)

    if "2" in top_level:
        print("\n" + "=" * 60)
        print(f"PHASE 2: Tagging concepts to sections ({book_id})")
        print("=" * 60)
        from scripts.tag_concepts import run_phase2
        await run_phase2(book_id)

    if phase3_subs:
        sub_labels = ", ".join(phase3_subs)
        print("\n" + "=" * 60)
        print(f"PHASE 3: Discovering relationships ({book_id}, sub-phases: {sub_labels})")
        print("=" * 60)
        from scripts.discover_relationships import run_phase3
        await run_phase3(book_id, sub_phases=phase3_subs)

    if "4" in top_level:
        print("\n" + "=" * 60)
        print(f"PHASE 4: Building final graph ({book_id})")
        print("=" * 60)
        # Guarantee section content is populated BEFORE embedding. Section
        # embeddings are built from title + content, so missing content
        # silently yields title-only vectors (the bug that left gulli_2025 /
        # arsanjani_2026 with empty passages). Idempotent: a no-op (returns 0)
        # for books whose content is already populated.
        from scripts.populate_content import populate_content
        populated = populate_content(book_id)
        print(f"Section content ensured: populated {populated} section(s) (0 = already present)")
        from scripts.build_graph import run_phase4
        await run_phase4(book_id)

    print("\n" + "=" * 60)
    print(f"PIPELINE COMPLETE for {book_id}")
    print("=" * 60)

    from iconsult_mcp.db import get_connection
    conn = get_connection()
    c = conn.execute("SELECT COUNT(*) FROM concepts WHERE book_id = ?", [book_id]).fetchone()[0]
    s = conn.execute("SELECT COUNT(*) FROM sections WHERE book_id = ?", [book_id]).fetchone()[0]
    r = conn.execute("SELECT COUNT(*) FROM relationships WHERE book_id = ?", [book_id]).fetchone()[0]
    print(f"\nFinal graph for {book_id}: {c} concepts, {s} sections, {r} relationships")


def main():
    parser = argparse.ArgumentParser(description="Run the iconsult knowledge graph pipeline")
    parser.add_argument(
        "--book",
        default=DEFAULT_BOOK_ID,
        help=f"Book ID from config.BOOKS (default: {DEFAULT_BOOK_ID}).",
    )
    parser.add_argument("--phase", nargs="+", help="Run specific phases (1a, 1b, 2, 3, 3a-3e, 4)")
    parser.add_argument("--reset", action="store_true", help="Clear THIS book's pipeline metadata first")
    args = parser.parse_args()

    if args.reset:
        reset_pipeline(args.book)

    asyncio.run(run_all(args.book, args.phase))


if __name__ == "__main__":
    main()
