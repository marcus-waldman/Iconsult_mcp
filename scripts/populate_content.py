"""
Populate sections.content from the book markdown file.

Reads each section's text using line_start/line_end, cleans LaTeX artifacts,
and stores the result in sections.content. Idempotent: skips sections that
already have content.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from iconsult_mcp.config import LITERATURE_DIR, BOOK_FILENAME
from iconsult_mcp.db import get_connection


def clean_section_text(text: str) -> str:
    """Strip LaTeX formatting artifacts from section text."""
    text = re.sub(r"\\section\*\{.*?\}", "", text)
    text = re.sub(r"\\begin\{figure\}.*?\\end\{figure\}", "[figure]", text, flags=re.DOTALL)
    text = re.sub(r"\\begin\{lstlisting\}.*?\\end\{lstlisting\}", "[code]", text, flags=re.DOTALL)
    text = re.sub(r"!\[.*?\]\(.*?\)", "[image]", text)
    return text.strip()


def main():
    conn = get_connection()

    # Load book
    book_path = LITERATURE_DIR / BOOK_FILENAME
    if not book_path.exists():
        print(f"Book file not found: {book_path}")
        sys.exit(1)
    book_lines = book_path.read_text(encoding="utf-8").splitlines()
    print(f"Loaded book: {len(book_lines)} lines")

    # Get sections that need content
    rows = conn.execute("""
        SELECT id, title, line_start, line_end
        FROM sections
        WHERE content IS NULL AND line_start IS NOT NULL AND line_end IS NOT NULL
        ORDER BY line_start
    """).fetchall()

    if not rows:
        print("All sections already have content populated.")
        return

    print(f"Populating content for {len(rows)} sections...")

    updated = 0
    for section_id, title, line_start, line_end in rows:
        # Lines are 1-indexed in the database
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
