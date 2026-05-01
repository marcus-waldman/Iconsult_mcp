"""
Phase 1b: Parse book markdown → sections table.

Splits the book on \\section*{} boundaries, maps sections to chapters
using the TOC (which has page numbers), and filters out front matter.

Content starts at line ~985 (Part 1). Chapter boundaries are marked by
standalone \\section*{N} followed by \\section*{Title}.
"""

import argparse
import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from iconsult_mcp.config import get_book_paths, list_registered_books
from iconsult_mcp.db import get_book, get_connection

DEFAULT_BOOK_ID = "arsanjani_2026"

SECTION_RE = re.compile(r"^\\section\*\{(.+?)\}\s*$")

# Hardcoded fallback values for arsanjani_2026 — used when the books row
# (chapter_boundaries) hasn't been seeded yet. Once the books table is
# populated via scripts/seed_books_table.py these are no longer consulted.
CONTENT_START_LINE = 985

CHAPTERS = [
    (1, "GenAI in the Enterprise: Landscape, Maturity, and Agent Focus", 1, 3),
    (2, "Agent-Ready LLMs: Selection, Deployment, and Adaptation", 1, 25),
    (3, "The Spectrum of LLM Adaptation for Agents: RAG to Fine-tuning", 1, 57),
    (4, "Agentic AI Architecture: Components and Interactions", 2, 95),
    (5, "Multi-Agent Coordination Patterns", 2, 119),
    (6, "Explainability and Compliance Agentic Patterns", 2, 183),
    (7, "Robustness and Fault Tolerance Patterns", 2, 205),
    (8, "Security and Trust Patterns for AI Agents", 2, 245),
    (9, "Human-Agent Interaction Patterns", 2, 281),
    (10, "Agent Cognition and Memory Patterns", 2, 311),
    (11, "System-Level Patterns and Inter-Agent Communication", 2, 339),
    (12, "Self-Improvement and Evaluation Patterns", 3, 367),
    (13, "Implementing a Foundational Agentic System with Google ADK", 3, 407),
    (14, "Implementing a Multi-Agent Architecture with CrewAI and LangGraph", 3, 467),
    (15, "From Blueprints to Impact: Practical Deployment and Measuring Value", 3, 507),
    (16, "The Future of Agentic AI", 3, 519),
]

CHAPTER_LINES = {
    1: 996, 2: 1415, 3: 2018, 4: 2806, 5: 3262, 6: 4807,
    7: 5342, 8: 7338, 9: 8049, 10: 8775, 11: 9532,
    12: 10427, 13: 10740, 14: 11483, 15: 12082, 16: 13155,
}


def load_boundaries_from_db(book_id: str) -> bool:
    """Populate module-level CHAPTERS / CHAPTER_LINES / CONTENT_START_LINE
    from books.chapter_boundaries. Returns True if loaded, False if absent.
    """
    global CHAPTERS, CHAPTER_LINES, CONTENT_START_LINE
    row = get_book(book_id)
    if not row or not row.get("chapter_boundaries"):
        return False
    boundaries = row["chapter_boundaries"]
    CONTENT_START_LINE = boundaries.get("content_start_line", CONTENT_START_LINE)
    chapters = boundaries.get("chapters", [])
    if not chapters:
        return False
    CHAPTERS = [
        (c["number"], c["title"], c["part"], c["page_start"]) for c in chapters
    ]
    CHAPTER_LINES = {
        c["number"]: c["line_start"] for c in chapters if c.get("line_start") is not None
    }
    return True


def slugify_section(title: str, chapter_number: int) -> str:
    """Create a bare section slug (no book prefix)."""
    slug = title.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    if len(slug) > 60:
        slug = slug[:60]
    return f"ch{chapter_number:02d}_{slug}"


def make_section_id(book_id: str, title: str, chapter_number: int) -> str:
    """Generate a book-namespaced section ID: `{book_id}__ch{NN}_{slug}`."""
    return f"{book_id}__{slugify_section(title, chapter_number)}"


def get_chapter_for_line(line_num: int) -> tuple[int, int] | None:
    """Given a line number, return (chapter_number, part_number) or None if before content."""
    if line_num < CONTENT_START_LINE:
        return None

    current_chapter = None
    for ch_num, ch_line in sorted(CHAPTER_LINES.items(), key=lambda x: x[1]):
        if line_num >= ch_line:
            current_chapter = ch_num
        else:
            break

    if current_chapter is None:
        return None

    part = next(p for c, _, p, _ in CHAPTERS if c == current_chapter)
    return current_chapter, part


def approx_page_for_line(line_num: int) -> int | None:
    """Estimate the page number for a given line number.

    Uses chapter boundaries as anchor points and interpolates.
    """
    # Build (line, page) anchor points from chapter data
    anchors = []
    for ch_num, _, _, page_start in CHAPTERS:
        if ch_num in CHAPTER_LINES:
            anchors.append((CHAPTER_LINES[ch_num], page_start))

    if not anchors:
        return None

    anchors.sort()

    # If before first anchor, extrapolate
    if line_num <= anchors[0][0]:
        return anchors[0][1]

    # If after last anchor, extrapolate from last two
    if line_num >= anchors[-1][0]:
        if len(anchors) >= 2:
            l1, p1 = anchors[-2]
            l2, p2 = anchors[-1]
            lines_per_page = (l2 - l1) / max(p2 - p1, 1)
            extra_pages = int((line_num - l2) / max(lines_per_page, 1))
            return p2 + extra_pages
        return anchors[-1][1]

    # Interpolate between two surrounding anchors
    for j in range(len(anchors) - 1):
        l1, p1 = anchors[j]
        l2, p2 = anchors[j + 1]
        if l1 <= line_num <= l2:
            if l2 == l1:
                return p1
            frac = (line_num - l1) / (l2 - l1)
            return p1 + int(frac * (p2 - p1))

    return None


def parse_book(book_path: Path, book_id: str) -> list[dict]:
    """Parse the book markdown into sections.

    Returns list of dicts with: id, title, chapter_number, part_number,
    line_start, line_end, approx_page_start, approx_page_end.
    """
    lines = book_path.read_text(encoding="utf-8").splitlines()

    # Find all \section*{} boundaries after content start
    section_markers = []  # (line_number, title)
    for i, line in enumerate(lines, start=1):
        if i < CONTENT_START_LINE:
            continue
        m = SECTION_RE.match(line.strip())
        if m:
            section_markers.append((i, m.group(1).strip()))

    # Filter out standalone chapter number sections and part dividers.
    # A chapter marker is \section*{N} where N is a chapter number,
    # immediately followed by the chapter title section.
    # We want to combine these into the chapter's first section.
    skip_lines = set()
    for idx, (line_num, title) in enumerate(section_markers):
        # Part dividers
        if title.startswith("Part ") and re.match(r"^Part \d+$", title):
            skip_lines.add(line_num)
            continue
        # Chapter number markers (standalone digits matching our chapter list)
        if re.match(r"^\d+$", title) and int(title) in CHAPTER_LINES:
            skip_lines.add(line_num)
            continue

    # Build sections from non-skipped markers
    filtered_markers = [(ln, t) for ln, t in section_markers if ln not in skip_lines]

    sections = []
    for idx, (line_start, title) in enumerate(filtered_markers):
        # Determine line_end (start of next section - 1)
        if idx + 1 < len(filtered_markers):
            line_end = filtered_markers[idx + 1][0] - 1
        else:
            line_end = len(lines)

        # Skip very short sections (likely artifacts)
        if line_end - line_start < 3:
            continue

        # Skip some non-content sections
        if title in ("Note", "Free Benefits with Your Book",
                      "Get This Book's PDF Version and Exclusive Extras",
                      "Share your thoughts"):
            continue

        ch_info = get_chapter_for_line(line_start)
        if ch_info is None:
            continue

        chapter_number, part_number = ch_info

        section_id = make_section_id(book_id, title, chapter_number)
        page_start = approx_page_for_line(line_start)
        page_end = approx_page_for_line(line_end)

        sections.append({
            "id": section_id,
            "title": title,
            "chapter_number": chapter_number,
            "part_number": part_number,
            "line_start": line_start,
            "line_end": line_end,
            "approx_page_start": page_start,
            "approx_page_end": page_end,
        })

    return sections


def insert_sections(sections: list[dict], book_id: str, book_path: Path):
    """Insert parsed sections (book-scoped) into the database."""
    conn = get_connection()

    metadata_key = f"book_hash:{book_id}"
    existing = conn.execute(
        "SELECT value FROM pipeline_metadata WHERE key = ?",
        [metadata_key],
    ).fetchone()

    current_hash = hashlib.md5(book_path.read_bytes()).hexdigest()

    if existing and existing[0] == current_hash:
        print(f"Book already parsed for {book_id} (hash {current_hash[:8]}). Skipping.")
        return

    conn.execute("DELETE FROM sections WHERE book_id = ?", [book_id])

    inserted = 0
    seen_ids = set()
    for s in sections:
        sid = s["id"]
        # Handle duplicate section IDs
        if sid in seen_ids:
            sid = f"{sid}_{s['line_start']}"
            s["id"] = sid
        seen_ids.add(sid)

        try:
            conn.execute(
                """INSERT INTO sections
                   (id, title, chapter_number, part_number,
                    line_start, line_end, approx_page_start, approx_page_end, book_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [sid, s["title"], s["chapter_number"], s["part_number"],
                 s["line_start"], s["line_end"],
                 s["approx_page_start"], s["approx_page_end"], book_id],
            )
            inserted += 1
        except Exception as e:
            print(f"  Warning: skipping section '{s['title']}': {e}")

    conn.execute(
        "INSERT OR REPLACE INTO pipeline_metadata (key, value) VALUES (?, ?)",
        [metadata_key, current_hash],
    )

    print(f"Inserted {inserted} sections from book for {book_id}.")


def main():
    parser = argparse.ArgumentParser(description="Parse a book markdown into the sections table.")
    parser.add_argument(
        "--book",
        default=DEFAULT_BOOK_ID,
        help=f"Book ID from config.BOOKS (default: {DEFAULT_BOOK_ID}).",
    )
    args = parser.parse_args()
    book_id = args.book

    if load_boundaries_from_db(book_id):
        print(f"Loaded chapter_boundaries for {book_id} from books table.")
    else:
        if book_id != DEFAULT_BOOK_ID:
            print(
                f"ERROR: No chapter_boundaries in books table for '{book_id}'. "
                "Run scripts/seed_books_table.py first."
            )
            sys.exit(1)
        print(f"Using hardcoded chapter_boundaries fallback for {book_id}.")

    paths = get_book_paths(book_id)
    book_path = paths["book"]
    if not book_path.exists():
        print(
            f"ERROR: Book file not found for '{book_id}': {book_path}\n"
            f"Registered books: {list_registered_books()}"
        )
        sys.exit(1)

    print(f"Parsing book for {book_id}: {book_path.name}")
    sections = parse_book(book_path, book_id)
    print(f"Found {len(sections)} sections across {len(set(s['chapter_number'] for s in sections))} chapters")

    # Print chapter breakdown
    from collections import Counter
    ch_counts = Counter(s["chapter_number"] for s in sections)
    for ch in sorted(ch_counts):
        title = next(t for c, t, _, _ in CHAPTERS if c == ch)
        print(f"  Ch {ch}: {ch_counts[ch]} sections — {title[:50]}")

    insert_sections(sections, book_id, book_path)


if __name__ == "__main__":
    main()
