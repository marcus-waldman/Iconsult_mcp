"""
Populate sections.content from a book's markdown file (book-scoped).

Reads each section's text using line_start/line_end, cleans LaTeX artifacts,
and stores the result in sections.content. Idempotent: skips sections that
already have content.
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from iconsult_mcp.config import get_book_paths, list_registered_books
from iconsult_mcp.db import get_connection

DEFAULT_BOOK_ID = "arsanjani_2026"


def clean_section_text(text: str) -> str:
    """Strip LaTeX formatting artifacts from section text."""
    text = re.sub(r"\\section\*\{.*?\}", "", text)
    text = re.sub(r"\\begin\{figure\}.*?\\end\{figure\}", "[figure]", text, flags=re.DOTALL)
    text = re.sub(r"\\begin\{lstlisting\}.*?\\end\{lstlisting\}", "[code]", text, flags=re.DOTALL)
    text = re.sub(r"!\[.*?\]\(.*?\)", "[image]", text)
    return text.strip()


def populate_content(book_id: str) -> int:
    """Populate `sections.content` for one book from its markdown file.

    Reads each NULL-content section's text via line_start/line_end, cleans
    LaTeX artifacts, and writes it to `sections.content`. Idempotent: sections
    that already have content are skipped, so re-running is a no-op that
    returns 0. Returns the number of sections updated. Raises FileNotFoundError
    if the book markdown is missing.

    Importable by `run_pipeline.py` so phase 4 can guarantee content exists
    before `generate_section_embeddings` (which embeds title + content).
    """
    conn = get_connection()

    book_path = get_book_paths(book_id)["book"]
    if not book_path.exists():
        raise FileNotFoundError(
            f"Book file not found for '{book_id}': {book_path}. "
            f"Registered books: {list_registered_books()}"
        )
    book_lines = book_path.read_text(encoding="utf-8").splitlines()

    # Only this book's sections that still need content.
    rows = conn.execute("""
        SELECT id, title, line_start, line_end
        FROM sections
        WHERE book_id = ? AND content IS NULL
          AND line_start IS NOT NULL AND line_end IS NOT NULL
        ORDER BY line_start
    """, [book_id]).fetchall()

    updated = 0
    for section_id, title, line_start, line_end in rows:
        text = "\n".join(book_lines[line_start - 1 : line_end])
        cleaned = clean_section_text(text)
        if not cleaned:
            continue
        conn.execute(
            "UPDATE sections SET content = ? WHERE id = ?",
            [cleaned, section_id],
        )
        updated += 1
    return updated


def main():
    parser = argparse.ArgumentParser(description="Populate sections.content from the book markdown.")
    parser.add_argument(
        "--book",
        default=DEFAULT_BOOK_ID,
        help=f"Book ID from config.BOOKS (default: {DEFAULT_BOOK_ID}).",
    )
    args = parser.parse_args()
    book_id = args.book

    try:
        updated = populate_content(book_id)
    except FileNotFoundError as e:
        print(e)
        sys.exit(1)

    if updated == 0:
        print(f"All sections for {book_id} already have content (nothing to populate).")
    else:
        print(f"Updated {updated} sections with content for {book_id}.")


if __name__ == "__main__":
    main()
