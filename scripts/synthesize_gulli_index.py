"""One-shot synthesizer: convert Gulli's chapter-reference index → page-numbered.

Phase 3 second-book ingestion. The Gulli 2025 INDEX.md uses chapter
references rather than page numbers (e.g., `- A/B Testing - Chapter 3:
Parallelization`), but the existing `parse_index.py` is built for the
Arsanjani-style page-numbered format. Rather than fork the parser, this
script pre-processes the Gulli index into Arsanjani-compatible form: each
concept's referenced chapter(s) are mapped to that chapter's start page,
emitted in dot-leader format.

Source: `literature/gulli_2025/Gulli - 2025 - INDEX.md`
Output: `literature/gulli_2025/Gulli - 2025 - INDEX-page-numbered.md`

Concepts whose only references are to non-numbered sections (Glossary,
Introduction, Appendix-only) are dropped — the pipeline scopes strictly to
numbered chapters and those concepts wouldn't get content tagged anyway.

Idempotent: re-running overwrites the output file.

    py scripts/synthesize_gulli_index.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from seed_books_table import GULLI_2025_CHAPTERS  # type: ignore  # noqa: E402

INPUT_PATH = (
    PROJECT_ROOT / "literature" / "gulli_2025" / "Gulli - 2025 - INDEX.md"
)
OUTPUT_PATH = (
    PROJECT_ROOT
    / "literature"
    / "gulli_2025"
    / "Gulli - 2025 - INDEX-page-numbered.md"
)

CHAPTER_START_PAGE: dict[int, int] = {
    c["number"]: c["page_start"] for c in GULLI_2025_CHAPTERS
}

# Match `Chapter N` (number captured) anywhere in a string.
CHAPTER_REF_RE = re.compile(r"\bChapter\s+(\d+)\b")


def _split_concept_and_refs(body: str) -> tuple[str, str] | None:
    """Split `ConceptName - Chapter N: Title, Chapter M: Title` into (name, refs).

    The Gulli index uses ` - ` (space-dash-space) as the separator between
    concept name and its chapter list. Concept names may themselves contain
    hyphens (e.g., `A2A (Agent-to-Agent)`), but only the spaced-dash variant
    is the separator. Returns None if no separator is found.
    """
    if " - " not in body:
        return None
    name, refs = body.split(" - ", 1)
    return name.strip(), refs.strip()


def synthesize_index(in_path: Path, out_path: Path) -> tuple[int, int, int]:
    """Read the chapter-reference index and emit a page-numbered version.

    Returns (concepts_emitted, lines_skipped_no_chapter_ref, lines_skipped_other).
    """
    if not in_path.exists():
        raise FileNotFoundError(f"Input index not found: {in_path}")

    emitted_lines: list[str] = [
        "% Synthesized from Gulli 2025 chapter-reference index by",
        "% scripts/synthesize_gulli_index.py. Page numbers are each concept's",
        "% referenced chapter start page (multiple chapters → multiple pages).",
        "% Concepts that only referenced non-numbered sections (Glossary,",
        "% Introduction, Appendix-only) were dropped.",
        "",
    ]

    concepts_emitted = 0
    skipped_no_chapter_ref = 0
    skipped_other = 0

    for raw in in_path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        stripped = line.strip()

        if not stripped:
            continue

        # Pass through letter-divider headings unchanged so the parser sees
        # the alphabetical structure.
        if re.match(r"^\\section\*\{[A-Z]\}$", stripped):
            emitted_lines.append(stripped)
            continue

        # Bullet entries: `- ConceptName - Chapter N: ...`
        if stripped.startswith("- "):
            body = stripped[2:].strip()
            split = _split_concept_and_refs(body)
            if split is None:
                skipped_other += 1
                continue

            name, refs = split

            # Find every chapter number in the refs portion. If the same
            # chapter is mentioned twice (rare in Gulli), dedupe via set.
            ch_nums = sorted({int(m.group(1)) for m in CHAPTER_REF_RE.finditer(refs)})

            if not ch_nums:
                # No "Chapter N" reference — likely Glossary/Introduction/
                # Appendix-only. Drop.
                skipped_no_chapter_ref += 1
                continue

            pages = sorted({
                CHAPTER_START_PAGE[n] for n in ch_nums if n in CHAPTER_START_PAGE
            })
            if not pages:
                skipped_no_chapter_ref += 1
                continue

            page_text = ", ".join(str(p) for p in pages)
            emitted_lines.append(f"{name} ..... {page_text}")
            concepts_emitted += 1
            continue

        # Other lines (prose, the trailing prompt-disclosure paragraph, etc.)
        # — drop. The Arsanjani-style parser only consumes letter dividers
        # and dot-leader / inline-page entries.
        skipped_other += 1

    out_path.write_text("\n".join(emitted_lines) + "\n", encoding="utf-8")
    return concepts_emitted, skipped_no_chapter_ref, skipped_other


def main() -> int:
    emitted, no_ref, other = synthesize_index(INPUT_PATH, OUTPUT_PATH)
    print(f"Wrote {OUTPUT_PATH}")
    print(f"  emitted concepts: {emitted}")
    print(f"  skipped (no chapter ref): {no_ref}")
    print(f"  skipped (other / prose): {other}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
