"""
Phase 2: Tag concepts to sections using Claude.

For each chapter's sections, sends the section text + concept list to Claude.
Claude identifies which concepts are discussed in each section, with confidence
scores and one-sentence summaries. Results go into concept_sections table
and concepts.definition gets updated.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from iconsult_mcp.config import LITERATURE_DIR, BOOK_FILENAME
from iconsult_mcp.db import get_connection
from iconsult_mcp.embed import claude_messages

# Maximum characters of section text to send per Claude call
MAX_CONTEXT_CHARS = 80_000


def get_chapter_sections(chapter_number: int) -> list[dict]:
    """Get all sections for a chapter from the database."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT id, title, line_start, line_end
        FROM sections
        WHERE chapter_number = ?
        ORDER BY line_start
    """, [chapter_number]).fetchall()

    return [
        {"id": r[0], "title": r[1], "line_start": r[2], "line_end": r[3]}
        for r in rows
    ]


def get_all_concepts() -> list[dict]:
    """Get all concepts from the database."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, name, page_references FROM concepts ORDER BY name"
    ).fetchall()
    return [{"id": r[0], "name": r[1], "pages": r[2]} for r in rows]


def get_section_text(line_start: int, line_end: int, book_lines: list[str]) -> str:
    """Extract section text from book lines."""
    # Lines are 1-indexed in the database
    text = "\n".join(book_lines[line_start - 1 : line_end])
    # Strip LaTeX formatting artifacts
    text = re.sub(r"\\section\*\{.*?\}", "", text)
    text = re.sub(r"\\begin\{figure\}.*?\\end\{figure\}", "[figure]", text, flags=re.DOTALL)
    text = re.sub(r"\\begin\{lstlisting\}.*?\\end\{lstlisting\}", "[code]", text, flags=re.DOTALL)
    text = re.sub(r"!\[.*?\]\(.*?\)", "[image]", text)
    return text.strip()


async def tag_chapter(
    chapter_number: int,
    book_lines: list[str],
    concepts: list[dict],
) -> list[dict]:
    """Use Claude to tag which concepts appear in each section of a chapter.

    Returns list of dicts: {concept_id, section_id, confidence, is_primary, definition}
    """
    sections = get_chapter_sections(chapter_number)
    if not sections:
        print(f"  No sections found for chapter {chapter_number}")
        return []

    # Build context: section texts
    section_texts = {}
    total_chars = 0
    for s in sections:
        text = get_section_text(s["line_start"], s["line_end"], book_lines)
        if total_chars + len(text) > MAX_CONTEXT_CHARS:
            text = text[: MAX_CONTEXT_CHARS - total_chars]
        section_texts[s["id"]] = text
        total_chars += len(text)
        if total_chars >= MAX_CONTEXT_CHARS:
            break

    # Build the section context for Claude
    section_context = ""
    for s in sections:
        if s["id"] in section_texts:
            section_context += f"\n\n--- SECTION: {s['id']} | {s['title']} ---\n"
            section_context += section_texts[s["id"]][:5000]  # Cap per section

    # Build concept list
    concept_list = "\n".join(
        f"- {c['name']} (id: {c['id']})"
        for c in concepts
    )

    prompt = f"""You are analyzing Chapter {chapter_number} of "Agentic Architectural Patterns for Building Multi-Agent Systems" to identify which concepts from the book's index are discussed in each section.

Here are all concepts from the index:

{concept_list}

Here are the sections from Chapter {chapter_number}:

{section_context}

For each concept that is substantively discussed (not merely mentioned in passing) in any section, provide:
1. concept_id: the concept's ID
2. section_id: the section where it's discussed
3. confidence: 0.0-1.0 (how confident you are this concept is meaningfully discussed here)
4. is_primary: true if this section is the primary/definitive discussion of this concept
5. definition: a one-sentence definition/summary of this concept based on the text

Respond with a JSON array. Only include entries with confidence >= 0.5. Example:
```json
[
  {{"concept_id": "agent_router_pattern", "section_id": "ch05_the_agent_router_pattern_intent_based_routing", "confidence": 0.95, "is_primary": true, "definition": "A pattern that routes incoming requests to specialized agents based on intent classification."}},
]
```

Return ONLY the JSON array, no other text."""

    response = await claude_messages(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=8192,
    )

    # Parse JSON from response
    # Handle markdown code blocks
    response = response.strip()
    if response.startswith("```"):
        response = re.sub(r"^```(?:json)?\s*", "", response)
        response = re.sub(r"\s*```$", "", response)

    try:
        results = json.loads(response)
        if not isinstance(results, list):
            print(f"  Warning: unexpected response format for chapter {chapter_number}")
            return []
        return results
    except json.JSONDecodeError as e:
        print(f"  Warning: failed to parse Claude response for chapter {chapter_number}: {e}")
        print(f"  Response preview: {response[:200]}")
        return []


async def run_phase2():
    """Run Phase 2: tag all concepts to sections."""
    conn = get_connection()

    # Idempotency check
    existing = conn.execute(
        "SELECT value FROM pipeline_metadata WHERE key = 'phase2_complete'"
    ).fetchone()
    if existing and existing[0] == "true":
        print("Phase 2 already complete. Skipping. (Delete pipeline_metadata key 'phase2_complete' to re-run)")
        return

    # Load book text
    book_path = LITERATURE_DIR / BOOK_FILENAME
    book_lines = book_path.read_text(encoding="utf-8").splitlines()

    concepts = get_all_concepts()
    print(f"Loaded {len(concepts)} concepts")

    # Get chapter numbers that have sections
    chapters = conn.execute(
        "SELECT DISTINCT chapter_number FROM sections ORDER BY chapter_number"
    ).fetchall()
    chapter_numbers = [r[0] for r in chapters]
    print(f"Processing {len(chapter_numbers)} chapters")

    all_tags = []
    definitions = {}  # concept_id -> best definition

    for ch_num in chapter_numbers:
        print(f"\n  Tagging Chapter {ch_num}...")
        tags = await tag_chapter(ch_num, book_lines, concepts)
        print(f"    Found {len(tags)} concept-section mappings")
        all_tags.extend(tags)

        # Collect definitions (prefer primary discussions)
        for tag in tags:
            cid = tag.get("concept_id")
            defn = tag.get("definition")
            if cid and defn:
                if cid not in definitions or tag.get("is_primary"):
                    definitions[cid] = defn

    # Insert concept_sections
    conn.execute("DELETE FROM concept_sections")
    inserted = 0
    for tag in all_tags:
        try:
            conn.execute("""
                INSERT INTO concept_sections (concept_id, section_id, confidence, is_primary)
                VALUES (?, ?, ?, ?)
            """, [
                tag["concept_id"],
                tag["section_id"],
                tag.get("confidence", 0.5),
                tag.get("is_primary", False),
            ])
            inserted += 1
        except Exception as e:
            # Skip invalid foreign keys etc.
            pass

    print(f"\nInserted {inserted} concept-section mappings")

    # Update concept definitions
    updated = 0
    for cid, defn in definitions.items():
        try:
            conn.execute(
                "UPDATE concepts SET definition = ? WHERE id = ?",
                [defn, cid],
            )
            updated += 1
        except Exception:
            pass

    print(f"Updated {updated} concept definitions")

    conn.execute("""
        INSERT OR REPLACE INTO pipeline_metadata (key, value)
        VALUES ('phase2_complete', 'true')
    """)


def main():
    import asyncio
    asyncio.run(run_phase2())


if __name__ == "__main__":
    main()
