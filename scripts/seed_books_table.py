"""
Seed the `books` table from the in-process registry (config.BOOKS).

Idempotent — safe to run repeatedly. Uses INSERT OR REPLACE under the hood.

Per-book metadata (title, authors, year, altitude, is_oracle) comes from
`config.BOOKS`. For arsanjani_2026 the chapter_boundaries JSON is built from
the existing `parse_book.CHAPTERS` + `CHAPTER_LINES` + `CONTENT_START_LINE`
constants so the source-of-truth migration is non-breaking; Phase 1c
swaps parse_book.py to read these values back from the books table.

Run after database initialization:

    py scripts/seed_books_table.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the project importable when run as a script
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from iconsult_mcp.config import BOOKS  # noqa: E402
from iconsult_mcp.db import close_connection, list_books, upsert_book  # noqa: E402


def _build_arsanjani_2026_boundaries() -> dict:
    """Reuse parse_book's hardcoded chapter data to build the JSON payload."""
    # Lazy import: parse_book lives under scripts/, not the package
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    import parse_book  # type: ignore

    chapters = []
    for ch_num, title, part, page_start in parse_book.CHAPTERS:
        chapters.append(
            {
                "number": ch_num,
                "title": title,
                "part": part,
                "page_start": page_start,
                "line_start": parse_book.CHAPTER_LINES.get(ch_num),
            }
        )
    return {
        "content_start_line": parse_book.CONTENT_START_LINE,
        "chapters": chapters,
    }


# Per-book chapter_boundaries builders. Add new entries as books are onboarded.
_BOUNDARY_BUILDERS = {
    "arsanjani_2026": _build_arsanjani_2026_boundaries,
}


def seed() -> int:
    """Upsert every registered book. Returns the number of rows seeded."""
    count = 0
    for book_id, meta in BOOKS.items():
        builder = _BOUNDARY_BUILDERS.get(book_id)
        boundaries = builder() if builder else None
        upsert_book(
            book_id=book_id,
            title=meta["title"],
            authors=meta.get("authors"),
            year=meta.get("year"),
            altitude=meta.get("altitude"),
            is_oracle=meta.get("is_oracle", False),
            chapter_boundaries=boundaries,
        )
        count += 1
        print(f"Seeded book: {book_id}")
    return count


def main() -> int:
    n = seed()
    rows = list_books()
    print(f"\n{n} book(s) seeded. Books table now contains:")
    for r in rows:
        chapters = r.get("chapter_boundaries", {})
        ch_count = len(chapters.get("chapters", [])) if isinstance(chapters, dict) else 0
        print(
            f"  {r['id']:<24}  oracle={r['is_oracle']!s:<5}  "
            f"altitude={r['altitude']:<14}  chapters={ch_count}"
        )
    close_connection()
    return 0


if __name__ == "__main__":
    sys.exit(main())
