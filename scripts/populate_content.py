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


def main():
    parser = argparse.ArgumentParser(description="Populate sections.content from the book markdown.")
    parser.add_argument(
        "--book",
        default=DEFAULT_BOOK_ID,
        help=f"Book ID from config.BOOKS (default: {DEFAULT_BOOK_ID}).",
    )
    args = parser.parse_args()
    book_id = args.book

    conn = get_connection()

    book_path = get_book_paths(book_id)["book"]
    if not book_path.exists():
        print(
            f"Book file not found for '{book_id}': {book_path}\n"
            f"Registered books: {list_registered_books()}"
        )
        sys.exit(1)
    book_lines = book_path.read_text(encoding="utf-8").splitlines()
    print(f"Loaded book for {book_id}: {len(book_lines)} lines")

    # Get this book's sections that still need content
    rows = conn.execute("""
        SELECT id, title, line_start, line_end
        FROM sections
        WHERE book_id = ? AND content IS NULL
          AND line_start IS NOT NULL AND line_end IS NOT NULL
        ORDER BY line_start
    """, [book_id]).fetchall()

    if not rows:
        print(f"All sections for {book_id} already have content populated.")
        return

    print(f"Populating content for {len(rows)} sections of {book_id}...")

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

    print(f"Updated {updated} sections with content.")


if __name__ == "__main__":
    main()
