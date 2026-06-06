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


# --- gulli_2025 -------------------------------------------------------------
# Source: Antonio Gulli, "Agentic Design Patterns: A Hands-On Guide to Building
# Intelligent Systems" (Springer Nature, December 2025), 424 pages.
#
# Line numbers were extracted from the Mathpix output at
# `literature/gulli_2025/Gulli - 2025- ...md` by grep'ing `\section*{Chapter
# N: ...}` markers. Page-start values were reconstructed from the TOC's
# per-chapter page-count column (book lines 11-44) cumulatively from a
# front-matter total of 18 pages; cross-checked against three explicit page
# refs in the TOC (Ch7→121, Ch11→182, Ch14→216, Ch21→330) — all matched
# within ±1 page.
#
# Parts: Part One = Chs 1-7 (foundational patterns), Part Two = Chs 8-11
# (memory/learning/MCP/goals), Part Three = Chs 12-14 (recovery/HITL/RAG),
# Part Four = Chs 15-21 (advanced/inter-agent/safety/eval). Appendices A-G
# are intentionally excluded — Phase 3 ingestion scopes strictly to numbered
# chapters; revisit if appendix content is needed downstream.
GULLI_2025_CHAPTERS: list[dict] = [
    {"number": 1,  "title": "Prompt Chaining",                "part": 1, "page_start": 19,  "line_start": 311},
    {"number": 2,  "title": "Routing",                        "part": 1, "page_start": 31,  "line_start": 548},
    {"number": 3,  "title": "Parallelization",                "part": 1, "page_start": 44,  "line_start": 938},
    {"number": 4,  "title": "Reflection",                     "part": 1, "page_start": 59,  "line_start": 1351},
    {"number": 5,  "title": "Tool Use",                       "part": 1, "page_start": 72,  "line_start": 1638},
    {"number": 6,  "title": "Planning",                       "part": 1, "page_start": 92,  "line_start": 2255},
    {"number": 7,  "title": "Multi-Agent Collaboration",      "part": 1, "page_start": 105, "line_start": 2545},
    {"number": 8,  "title": "Memory Management",              "part": 2, "page_start": 122, "line_start": 2982},
    {"number": 9,  "title": "Learning and Adaptation",        "part": 2, "page_start": 143, "line_start": 3540},
    {"number": 10, "title": "Model Context Protocol",         "part": 2, "page_start": 155, "line_start": 3717},
    {"number": 11, "title": "Goal Setting and Monitoring",    "part": 2, "page_start": 171, "line_start": 4040},
    {"number": 12, "title": "Exception Handling and Recovery","part": 3, "page_start": 183, "line_start": 4372},
    {"number": 13, "title": "Human-in-the-Loop",              "part": 3, "page_start": 191, "line_start": 4505},
    {"number": 14, "title": "Knowledge Retrieval (RAG)",      "part": 3, "page_start": 200, "line_start": 4658},
    {"number": 15, "title": "Inter-Agent Communication (A2A)","part": 4, "page_start": 217, "line_start": 4956},
    {"number": 16, "title": "Resource-Aware Optimization",    "part": 4, "page_start": 232, "line_start": 5314},
    {"number": 17, "title": "Reasoning Techniques",           "part": 4, "page_start": 247, "line_start": 5735},
    {"number": 18, "title": "Guardrails/Safety Patterns",     "part": 4, "page_start": 271, "line_start": 6147},
    {"number": 19, "title": "Evaluation and Monitoring",      "part": 4, "page_start": 290, "line_start": 6725},
    {"number": 20, "title": "Prioritization",                 "part": 4, "page_start": 308, "line_start": 7098},
    {"number": 21, "title": "Exploration and Discovery",      "part": 4, "page_start": 318, "line_start": 7367},
]
# `\section*{Chapter 1: ...}` is line 311, but Chapter 1's slug is generated
# from that title-bearing marker itself, so CONTENT_START_LINE stays at 311.
GULLI_2025_CONTENT_START_LINE = 311


def _build_gulli_2025_boundaries() -> dict:
    return {
        "content_start_line": GULLI_2025_CONTENT_START_LINE,
        "chapters": list(GULLI_2025_CHAPTERS),
    }


# --- bratanic_2025 ----------------------------------------------------------
# Source: Tomaž Bratanič & Oskar Hane, "Essential GraphRAG: Knowledge
# Graph-Enhanced RAG" (Manning, July 2025), 176 pages.
#
# Single Mathpix export, split into corpus files by
# `scripts/prepare_bratanic_2025.py` (book = chapters 1-8 only; Appendix A,
# references, and marketing trimmed off). `line_start` values use Python
# splitlines() numbering — verified against the trimmed book file via
# `scripts/prepare_bratanic_2025.py` anchors. Chapters 2/4/7 head with a
# `\title{}` (or plain) line rather than `\section*{}`, so their `line_start`
# anchors on the chapter's first `\section*{This chapter covers}` marker.
# `page_start` values come from the book's `contents` TOC (lines 64-124).
# The book has no Parts, so every chapter is part 1.
BRATANIC_2025_CHAPTERS: list[dict] = [
    {"number": 1, "title": "Improving LLM accuracy",                              "part": 1, "page_start": 1,   "line_start": 218},
    {"number": 2, "title": "Vector similarity search and hybrid search",         "part": 1, "page_start": 17,  "line_start": 474},
    {"number": 3, "title": "Advanced vector retrieval strategies",               "part": 1, "page_start": 30,  "line_start": 954},
    {"number": 4, "title": "Generating Cypher queries from natural language questions", "part": 1, "page_start": 45, "line_start": 1334},
    {"number": 5, "title": "Agentic RAG",                                         "part": 1, "page_start": 56,  "line_start": 1706},
    {"number": 6, "title": "Constructing knowledge graphs with LLMs",            "part": 1, "page_start": 70,  "line_start": 2220},
    {"number": 7, "title": "Microsoft's GraphRAG implementation",                "part": 1, "page_start": 88,  "line_start": 2692},
    {"number": 8, "title": "RAG application evaluation",                          "part": 1, "page_start": 116, "line_start": 3586},
]
BRATANIC_2025_CONTENT_START_LINE = 218


def _build_bratanic_2025_boundaries() -> dict:
    return {
        "content_start_line": BRATANIC_2025_CONTENT_START_LINE,
        "chapters": list(BRATANIC_2025_CHAPTERS),
    }


# Per-book chapter_boundaries builders. Add new entries as books are onboarded.
_BOUNDARY_BUILDERS = {
    "arsanjani_2026": _build_arsanjani_2026_boundaries,
    "gulli_2025": _build_gulli_2025_boundaries,
    "bratanic_2025": _build_bratanic_2025_boundaries,
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
