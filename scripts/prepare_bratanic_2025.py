"""One-shot: derive the corpus files for `bratanic_2025` from the Mathpix source.

Essential GraphRAG (Bratanič & Hane, Manning 2025) was extracted by Mathpix into
a single markdown file containing front matter, 8 numbered chapters, Appendix A,
references, the back-of-book index, and marketing back matter. This script splits
that into the two files the pipeline expects:

  literature/bratanic_2025/Bratanic and Hane - 2025 - Essential GraphRAG.md
      Front matter + chapters 1-8 (lines 1..3905). Trimmed before
      `\\section*{appendix}` (line 3906) so back matter does not fold into ch8
      (parse_book.py has no upper content bound). Mirrors the gulli "numbered
      chapters only" ingestion scope; Appendix A is intentionally excluded.

  literature/bratanic_2025/Bratanic and Hane - 2025 - INDEX.md
      The alphabetical back-of-book index (lines 4911..5115), already in the
      arsanjani-style letter-divider + inline-page format that parse_index.py
      consumes directly. No synthesize step needed.

Line numbers use Python str.splitlines() numbering, identical to parse_book.py.
Re-run if the upstream Mathpix output changes (pass --src to point at it).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEST_DIR = PROJECT_ROOT / "literature" / "bratanic_2025"

DEFAULT_SRC = Path(
    r"C:\Users\marcu\Downloads"
    r"\Essential GraphRAG_ Knowledge Graph-Enhanced RAG -- "
    r"Tomaž Bratanic, Oskar Hane -- 1, 2025 -- Manning.md"
)

BOOK_FILENAME = "Bratanic and Hane - 2025 - Essential GraphRAG.md"
INDEX_FILENAME = "Bratanic and Hane - 2025 - INDEX.md"

# 1-indexed, inclusive line ranges (Python splitlines numbering).
BOOK_LAST_LINE = 3905   # end of ch8 "Summary"; \section*{appendix} starts at 3906
INDEX_FIRST_LINE = 4911  # \section*{A}
INDEX_LAST_LINE = 5115   # last index entry before \section*{RELATED MANNING TITLES} (5116)


def _slice(lines: list[str], first: int, last: int) -> str:
    """Return lines[first..last] inclusive (1-indexed) joined with newlines."""
    chunk = lines[first - 1:last]
    return "\n".join(chunk) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC,
                        help="Path to the Mathpix-extracted source markdown.")
    args = parser.parse_args()

    src: Path = args.src
    if not src.exists():
        print(f"ERROR: source markdown not found: {src}")
        return 1

    lines = src.read_text(encoding="utf-8").splitlines()
    total = len(lines)
    if total < INDEX_LAST_LINE:
        print(
            f"ERROR: source has {total} lines but index is expected at "
            f"{INDEX_FIRST_LINE}-{INDEX_LAST_LINE}. Did the Mathpix output change? "
            "Re-derive the line ranges."
        )
        return 1

    # Sanity-check the anchors so a changed source fails loudly rather than
    # silently producing a mis-sliced corpus.
    if not lines[BOOK_LAST_LINE].lstrip().startswith(r"\section*{appendix}"):
        print(
            f"WARNING: line {BOOK_LAST_LINE + 1} is not '\\section*{{appendix}}' "
            f"(found: {lines[BOOK_LAST_LINE]!r}). Verify BOOK_LAST_LINE."
        )
    if not lines[INDEX_FIRST_LINE - 1].strip() == r"\section*{A}":
        print(
            f"WARNING: line {INDEX_FIRST_LINE} is not '\\section*{{A}}' "
            f"(found: {lines[INDEX_FIRST_LINE - 1]!r}). Verify INDEX_FIRST_LINE."
        )

    DEST_DIR.mkdir(parents=True, exist_ok=True)

    book_text = _slice(lines, 1, BOOK_LAST_LINE)
    index_text = _slice(lines, INDEX_FIRST_LINE, INDEX_LAST_LINE)

    book_path = DEST_DIR / BOOK_FILENAME
    index_path = DEST_DIR / INDEX_FILENAME
    book_path.write_text(book_text, encoding="utf-8")
    index_path.write_text(index_text, encoding="utf-8")

    print(f"Source: {src.name} ({total} lines)")
    print(f"  book  -> {book_path.relative_to(PROJECT_ROOT)}  "
          f"(lines 1-{BOOK_LAST_LINE}, {BOOK_LAST_LINE} lines)")
    print(f"  index -> {index_path.relative_to(PROJECT_ROOT)}  "
          f"(lines {INDEX_FIRST_LINE}-{INDEX_LAST_LINE}, "
          f"{INDEX_LAST_LINE - INDEX_FIRST_LINE + 1} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
