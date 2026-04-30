"""
Phase 2a: Generate `books.summary` and `books.summary_embedding`.

Hybrid workflow — Claude drafts, the user finalizes, the script embeds.

Modes
-----

    py scripts/generate_book_summary.py --book <book_id> --draft
        Generate a Claude draft summary from Ch. 1 + TOC + first chapter
        of Ch. 12 (the book's "abstract" content). Writes to
        literature/{book_id}/summary.md. Does NOT touch the database.
        Idempotent — overwrites any existing draft.

    py scripts/generate_book_summary.py --book <book_id> --commit
        Read literature/{book_id}/summary.md (presumed user-finalized),
        embed it via OpenAI text-embedding-3-small, and UPDATE the
        books row's `summary` + `summary_embedding`. Idempotent —
        re-running after edits refreshes both fields.

    py scripts/generate_book_summary.py --book <book_id> --show
        Print the stored summary state from the books table. Debug aid.

The summary is the basis for triage cosine match (Phase 2b's `triage_books`
tool), so it should describe *what a project would need this book for*,
not the table of contents.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from iconsult_mcp.config import (  # noqa: E402
    get_book_paths,
    list_registered_books,
)
from iconsult_mcp.db import (  # noqa: E402
    close_connection,
    get_book,
    set_book_summary,
)
from iconsult_mcp.embed import claude_messages, embed_query  # noqa: E402

DEFAULT_BOOK_ID = "arsanjani_2026"

# Sanity-check bounds for a finalized summary. Loose on purpose — Phase 6
# books may run a bit shorter or longer than the 500-1000 word target.
_MIN_SUMMARY_CHARS = 500
_MAX_SUMMARY_CHARS = 12_000


# --- Draft generation (Claude) ----------------------------------------------


def _read_book_lines(book_id: str) -> list[str]:
    book_path = get_book_paths(book_id)["book"]
    return book_path.read_text(encoding="utf-8").splitlines()


def _extract_chapter_text(
    lines: list[str],
    chapter_number: int,
    chapters: list[dict],
    max_chars: int = 8000,
) -> str:
    """Pull the first ~max_chars of a chapter's body using line_start anchors."""
    by_num = {c["number"]: c for c in chapters if c.get("line_start") is not None}
    if chapter_number not in by_num:
        return ""

    sorted_nums = sorted(by_num.keys(), key=lambda n: by_num[n]["line_start"])
    start_line = by_num[chapter_number]["line_start"]
    next_starts = [
        by_num[n]["line_start"] for n in sorted_nums if by_num[n]["line_start"] > start_line
    ]
    end_line = next_starts[0] if next_starts else len(lines)

    # lines list is 0-indexed but the chapter_boundaries values are 1-indexed
    body = "\n".join(lines[start_line - 1 : end_line - 1]).strip()
    if len(body) > max_chars:
        body = body[:max_chars] + "\n\n[...truncated...]"
    return body


def _build_toc(chapters: list[dict]) -> str:
    rows = []
    for c in chapters:
        rows.append(f"  Ch. {c['number']:>2}: {c['title']}")
    return "\n".join(rows)


def _build_draft_prompt(book_id: str, book_row: dict) -> tuple[str, str]:
    """Return (system_prompt, user_message) for the Claude draft call."""
    chapters = (book_row.get("chapter_boundaries") or {}).get("chapters") or []
    toc = _build_toc(chapters) if chapters else "(table of contents unavailable)"

    lines = _read_book_lines(book_id)
    ch1_text = _extract_chapter_text(lines, 1, chapters, max_chars=8000)
    # Ch. 12 of arsanjani_2026 is the rubric source ("Self-Improvement and
    # Evaluation Patterns"). For other books this still grabs whatever lives
    # at chapter 12 — usually a meaty pattern chapter, fine as a sample.
    ch12_text = _extract_chapter_text(lines, 12, chapters, max_chars=6000)
    if not ch12_text:
        # Books with fewer than 12 chapters: fall back to the last chapter.
        last_ch = max((c["number"] for c in chapters if c.get("line_start")), default=None)
        if last_ch:
            ch12_text = _extract_chapter_text(lines, last_ch, chapters, max_chars=6000)

    title = book_row.get("title") or book_id
    authors = book_row.get("authors") or "(unknown authors)"
    year = book_row.get("year") or "?"
    altitude = book_row.get("altitude") or "(unspecified altitude)"

    system_prompt = (
        "You are summarizing a software-architecture book for a TRIAGE LAYER. "
        "The summary will be embedded into a 1536-dim vector and matched via "
        "cosine similarity against project descriptions. Your goal is to "
        "produce text that scores HIGH against project descriptions for which "
        "this book is genuinely useful, and LOW against descriptions for which "
        "it is not.\n\n"
        "Constraints:\n"
        "  * 500–1000 words.\n"
        "  * Plain prose, no bullet lists, no headings, no markdown.\n"
        "  * Describe WHAT A PROJECT WOULD NEED THIS BOOK FOR — what kinds of "
        "system, what scale, what failure modes, what design questions.\n"
        "  * Use rich domain vocabulary the book actually uses (architectural "
        "patterns, the specific terminology, named techniques).\n"
        "  * Mention the book's altitude (e.g., mid-level patterns, "
        "implementation-level, strategic) and where it sits in a broader stack.\n"
        "  * Do NOT recite the table of contents. Do NOT enumerate chapters.\n"
        "  * Open with one sentence naming the book and its central thesis. "
        "Do not use phrases like 'this summary' or 'this book covers'."
    )

    user_message = (
        f"Book metadata:\n"
        f"  Title: {title}\n"
        f"  Authors: {authors}\n"
        f"  Year: {year}\n"
        f"  Altitude: {altitude}\n\n"
        f"Table of contents:\n{toc}\n\n"
        f"Chapter 1 (intro) excerpt:\n"
        f"---\n{ch1_text}\n---\n\n"
        f"Chapter 12 (representative pattern chapter) excerpt:\n"
        f"---\n{ch12_text}\n---\n\n"
        f"Write the triage-oriented summary now."
    )

    return system_prompt, user_message


async def _generate_draft(book_id: str, book_row: dict) -> str:
    system_prompt, user_message = _build_draft_prompt(book_id, book_row)
    text = await claude_messages(
        messages=[{"role": "user", "content": user_message}],
        system=system_prompt,
        max_tokens=2000,
    )
    return text.strip()


def _summary_path(book_id: str) -> Path:
    return get_book_paths(book_id)["base"] / "summary.md"


async def cmd_draft(book_id: str) -> int:
    book_row = get_book(book_id)
    if book_row is None:
        print(
            f"ERROR: book '{book_id}' not in books table. "
            "Run `py scripts/seed_books_table.py` first.",
            file=sys.stderr,
        )
        return 2

    print(f"Generating draft summary for {book_id} via Claude...")
    summary = await _generate_draft(book_id, book_row)

    out = _summary_path(book_id)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(summary + "\n", encoding="utf-8")

    word_count = len(summary.split())
    print(
        f"Wrote draft to {out.relative_to(PROJECT_ROOT)} "
        f"({len(summary)} chars, ~{word_count} words)."
    )
    print("Review/edit the draft, then re-run with --commit to embed and store.")
    return 0


# --- Commit (file → embedding → DB) -----------------------------------------


async def cmd_commit(book_id: str) -> int:
    book_row = get_book(book_id)
    if book_row is None:
        print(
            f"ERROR: book '{book_id}' not in books table. "
            "Run `py scripts/seed_books_table.py` first.",
            file=sys.stderr,
        )
        return 2

    src = _summary_path(book_id)
    if not src.exists():
        print(
            f"ERROR: {src.relative_to(PROJECT_ROOT)} not found. "
            "Run with --draft first to generate one.",
            file=sys.stderr,
        )
        return 2

    summary = src.read_text(encoding="utf-8").strip()
    n = len(summary)
    if n < _MIN_SUMMARY_CHARS:
        print(
            f"ERROR: summary is only {n} chars (min {_MIN_SUMMARY_CHARS}). "
            "Did you delete the draft body?",
            file=sys.stderr,
        )
        return 2
    if n > _MAX_SUMMARY_CHARS:
        print(
            f"ERROR: summary is {n} chars (max {_MAX_SUMMARY_CHARS}). "
            "Trim it before committing.",
            file=sys.stderr,
        )
        return 2

    print(f"Embedding {n}-char summary for {book_id}...")
    embedding = await embed_query(summary)
    print(f"Got {len(embedding)}-dim embedding. Writing to books table...")

    set_book_summary(book_id, summary, embedding)

    refreshed = get_book(book_id)
    print(
        f"OK. books.summary length = {len(refreshed['summary'])} chars; "
        f"has_summary_embedding = {refreshed['has_summary_embedding']}."
    )
    return 0


# --- Show (debug) -----------------------------------------------------------


def cmd_show(book_id: str) -> int:
    book_row = get_book(book_id)
    if book_row is None:
        print(f"book '{book_id}' not found.")
        return 2
    summary = book_row.get("summary")
    print(f"id:                    {book_row['id']}")
    print(f"title:                 {book_row['title']}")
    print(f"summary:               {len(summary) if summary else 0} chars")
    print(f"has_summary_embedding: {book_row['has_summary_embedding']}")
    if summary:
        preview = summary[:300].replace("\n", " ")
        print(f"summary preview:       {preview}...")
    return 0


# --- Entry point ------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate / commit / inspect books.summary + summary_embedding.",
    )
    parser.add_argument(
        "--book",
        default=DEFAULT_BOOK_ID,
        choices=list_registered_books(),
        help=f"Registered book_id (default: {DEFAULT_BOOK_ID}).",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--draft",
        action="store_true",
        help="Claude-generate summary draft to literature/{book_id}/summary.md.",
    )
    mode.add_argument(
        "--commit",
        action="store_true",
        help="Embed literature/{book_id}/summary.md and store in books table.",
    )
    mode.add_argument(
        "--show",
        action="store_true",
        help="Print stored summary state for the book.",
    )
    args = parser.parse_args()

    try:
        if args.show:
            return cmd_show(args.book)
        if args.draft:
            return asyncio.run(cmd_draft(args.book))
        if args.commit:
            return asyncio.run(cmd_commit(args.book))
        return 2
    finally:
        close_connection()


if __name__ == "__main__":
    sys.exit(main())
