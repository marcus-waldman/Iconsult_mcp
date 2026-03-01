"""
Phase 1a: Parse INDEX.md → concepts table.

Extracts concept names and page references from the book index.
Handles OCR artifacts like merged page numbers ("354 patterncontext355").

Top-level entries become graph nodes. Structural sub-entries (context, problem,
solution, consequences, guidance, implementation example) are discarded.
Named sub-entries (like "Blackboard Knowledge Hub") become their own nodes.
"""

import hashlib
import re
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from iconsult_mcp.config import LITERATURE_DIR, INDEX_FILENAME
from iconsult_mcp.db import get_connection

# Sub-entry labels that are structural metadata, not standalone concepts
STRUCTURAL_SUBENTRIES = {
    "context", "problem", "solution", "consequences", "forces",
    "guidance, implementation", "implementation example", "implementation, example",
    "example", "resources and further reading",
    "guidance implementation", "audit trail", "coherence and stability",
    "conflict detection", "escalation paths, defining", "resilience, testing",
    "game-theoretic resolution", "hierarchical resolution",
    "negotiation process", "policy-based resolution",
}

# Section divider patterns in the index (e.g. \section*{B}, \section*{F})
SECTION_DIVIDER_RE = re.compile(r"^\\section\*\{([A-Z])\}$")
# Named section entries (e.g. \section*{Knowledge Sharing pattern})
NAMED_SECTION_RE = re.compile(r"^\\section\*\{(.+?)\}(.*)$")
# LaTeX table entries
TABLE_ENTRY_RE = re.compile(r"^(.+?)\s*&\s*\$?([0-9, \\{}\-]+)\$?\s*\\\\?$")
# Page number patterns
PAGE_NUM_RE = re.compile(r"\d+")
# Dot leader line: "Concept name ..... 123" or "Concept name ..... 123, 456"
DOT_LEADER_RE = re.compile(r"^(.+?)\s*\.{2,}\s*(.+)$")
# Line with just a concept and page: "Concept name 123" or "Concept name 123, 456"
INLINE_PAGE_RE = re.compile(r"^(.+?)\s+(\d[\d, \-]+)$")


def slugify(name: str) -> str:
    """Convert a concept name to a slug ID."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    if len(slug) > 80:
        slug = slug[:80] + "_" + hashlib.md5(name.encode()).hexdigest()[:6]
    return slug


def parse_page_refs(text: str) -> list[int]:
    """Extract page numbers from a page reference string.

    Handles: "123", "123, 456", "60-63", "$60-63$", "483,486-488",
    and OCR artifacts like "354 patterncontext355".
    """
    # Remove LaTeX math markers and bold markers
    text = re.sub(r"[\$\\mathbf{}]", "", text)
    # Remove stray text merged with numbers (OCR artifacts)
    text = re.sub(r"[a-zA-Z()\[\]]+", " ", text)

    pages = set()
    # Split on commas and spaces
    for part in re.split(r"[,\s]+", text):
        part = part.strip()
        if not part:
            continue
        # Handle ranges like "60-63"
        range_match = re.match(r"(\d+)\s*-\s*(\d+)", part)
        if range_match:
            start, end = int(range_match.group(1)), int(range_match.group(2))
            if end - start < 50:  # sanity check
                for p in range(start, end + 1):
                    pages.add(p)
        elif re.match(r"^\d+$", part):
            pages.add(int(part))

    return sorted(pages)


def is_structural_subentry(name: str) -> bool:
    """Check if a line is a structural sub-entry (not a standalone concept)."""
    normalized = name.lower().strip().rstrip(":")
    # Remove leading dash/bullet
    normalized = re.sub(r"^[-•*]\s*", "", normalized)

    if normalized in STRUCTURAL_SUBENTRIES:
        return True

    # Patterns like "compliance request, routing" or "loan application lifecycle"
    # These are examples/specifics, not standalone concepts
    # But named patterns like "Blackboard Knowledge Hub" are concepts
    # Heuristic: if it starts lowercase, it's likely a sub-entry
    if name.strip() and name.strip()[0].islower():
        return True

    return False


def parse_index(index_path: Path) -> list[dict]:
    """Parse the INDEX.md file and extract concepts with page references.

    Returns a list of dicts with keys: name, pages, id.
    """
    text = index_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    concepts = {}  # name -> set of pages
    in_table = False
    orphan_names = []  # names waiting for page numbers (Pattern 4 region)
    orphan_pages = []  # page numbers waiting to be matched

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1

        if not line:
            continue

        # Skip table delimiters
        if line.startswith("\\begin{tabular}") or line.startswith("\\end{tabular}"):
            in_table = not in_table if line.startswith("\\begin") else False
            continue

        # LaTeX table entries
        if in_table:
            m = TABLE_ENTRY_RE.match(line)
            if m:
                name = m.group(1).strip().rstrip(",")
                pages = parse_page_refs(m.group(2))
                if not is_structural_subentry(name) and pages:
                    if name not in concepts:
                        concepts[name] = set()
                    concepts[name].update(pages)
            continue

        # Single-letter section dividers (\section*{B})
        if SECTION_DIVIDER_RE.match(line):
            continue

        # Single letter line (e.g. "B", "C", "N") - alphabet dividers
        if re.match(r"^[A-Z]$", line):
            continue

        # Named \section*{...} entries
        m = NAMED_SECTION_RE.match(line)
        if m:
            inner = m.group(1).strip()
            rest = m.group(2).strip()

            # Skip single-letter dividers inside \section*{}
            if re.match(r"^[A-Z]$", inner):
                continue

            # Clean up LaTeX escapes and trailing page numbers in name
            inner = inner.replace("\\\\", " ").replace("\\", "").strip()
            # Remove trailing page numbers from the name (e.g. "Iterative Debate for Robust Reasoning 6")
            inner = re.sub(r"\s+\d+\s*$", "", inner).strip()

            # Extract page numbers from the section name itself or trailing text
            pages_from_name = parse_page_refs(inner)
            # Remove page numbers from the name
            name = re.sub(r"\s*\d[\d, \-]*\s*$", "", inner).strip()

            pages_from_rest = parse_page_refs(rest) if rest else []

            all_pages = set(pages_from_name + pages_from_rest)

            if name and not is_structural_subentry(name):
                if name not in concepts:
                    concepts[name] = set()
                concepts[name].update(all_pages)

                # Check if rest has merged text (e.g. "identity provider (IdP)360")
                rest_name_match = re.match(r"^([a-zA-Z].*?)(\d+)$", rest)
                if rest_name_match:
                    sub_name = rest_name_match.group(1).strip()
                    sub_page = int(rest_name_match.group(2))
                    if not is_structural_subentry(sub_name):
                        if sub_name not in concepts:
                            concepts[sub_name] = set()
                        concepts[sub_name].add(sub_page)
            continue

        # Dot-leader lines: "Concept ..... 123"
        m = DOT_LEADER_RE.match(line)
        if m:
            name = m.group(1).strip()
            page_text = m.group(2).strip()

            # Handle OCR artifacts: "389 pattern" -> pages=[389], concept gets "pattern" dropped
            # Also "354 patterncontext355" -> pages=[354, 355]
            pages = parse_page_refs(page_text)

            if not is_structural_subentry(name) and pages:
                if name not in concepts:
                    concepts[name] = set()
                concepts[name].update(pages)
            continue

        # Inline page numbers: "Concept name 123, 456"
        m = INLINE_PAGE_RE.match(line)
        if m:
            name = m.group(1).strip()
            pages = parse_page_refs(m.group(2))

            if not is_structural_subentry(name) and pages:
                if name not in concepts:
                    concepts[name] = set()
                concepts[name].update(pages)
            continue

        # Lines that are just numbers (Pattern 4 region where names and numbers are separated)
        if re.match(r"^[\d, \-]+$", line):
            orphan_pages.extend(parse_page_refs(line))
            continue

        # Lines that are just text (no numbers) - potential concept names waiting for pages
        if not re.search(r"\d", line) and not line.startswith("\\"):
            if not is_structural_subentry(line):
                orphan_names.append(line)
            continue

    # Convert to list with cleanup
    result = []
    for name, pages in concepts.items():
        # Clean name: remove trailing commas, digits glued to end
        name = re.sub(r"\d+,?\s*$", "", name).strip().rstrip(",").strip()
        # Remove leading/trailing punctuation
        name = name.strip("-•* ")

        # Skip very short, numeric-only, or clearly non-concept entries
        if len(name) < 3:
            continue
        if re.match(r"^[\d, \-]+$", name):
            continue
        # Skip entries that are just page ranges
        if re.match(r"^\d+[-–]\d+$", name):
            continue

        concept_id = slugify(name)
        result.append({
            "id": concept_id,
            "name": name,
            "pages": sorted(pages),
        })

    # Sort by name for deterministic output
    result.sort(key=lambda c: c["name"].lower())
    return result


def insert_concepts(concepts: list[dict]):
    """Insert parsed concepts into the database."""
    conn = get_connection()

    # Check pipeline metadata for idempotency
    existing = conn.execute(
        "SELECT value FROM pipeline_metadata WHERE key = 'index_hash'"
    ).fetchone()

    index_path = LITERATURE_DIR / INDEX_FILENAME
    import hashlib as hl
    current_hash = hl.md5(index_path.read_bytes()).hexdigest()

    if existing and existing[0] == current_hash:
        print(f"Index already parsed (hash {current_hash[:8]}). Skipping.")
        return

    # Clear existing concepts (re-parse)
    conn.execute("DELETE FROM concepts")

    inserted = 0
    for c in concepts:
        try:
            conn.execute(
                "INSERT INTO concepts (id, name, page_references) VALUES (?, ?, ?)",
                [c["id"], c["name"], c["pages"]],
            )
            inserted += 1
        except Exception as e:
            # Handle duplicate IDs from slugification collisions
            print(f"  Warning: skipping duplicate concept '{c['name']}': {e}")

    # Record hash
    conn.execute("""
        INSERT OR REPLACE INTO pipeline_metadata (key, value)
        VALUES ('index_hash', ?)
    """, [current_hash])

    print(f"Inserted {inserted} concepts from index.")


def main():
    index_path = LITERATURE_DIR / INDEX_FILENAME
    if not index_path.exists():
        print(f"ERROR: Index file not found: {index_path}")
        sys.exit(1)

    print(f"Parsing index: {index_path.name}")
    concepts = parse_index(index_path)
    print(f"Found {len(concepts)} concepts")

    # Print sample
    for c in concepts[:10]:
        print(f"  {c['name']} -> pages {c['pages']}")
    if len(concepts) > 10:
        print(f"  ... and {len(concepts) - 10} more")

    insert_concepts(concepts)


if __name__ == "__main__":
    main()
