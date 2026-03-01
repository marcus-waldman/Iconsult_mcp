"""
Phase 3: Discover relationships between concepts.

Phase 3a — Explicit: Claude reads chapter text and identifies author-stated
relationships between concepts. High confidence (0.7–1.0), source_type="explicit".

Phase 3b — Semantic: Embed concepts, compute pairwise cosine similarity,
send high-similarity pairs to Claude for validation. Lower confidence (0.3–0.7),
source_type="semantic".

Phase 3c — Cross-Chapter Knowledge: Claude identifies relationships using domain
knowledge and concept definitions, without chapter text. source_type="cross_chapter_knowledge".

Phase 3d — Cross-Chapter Semantic: Embedding-based discovery of relationships between
concepts that never co-occurred in the same chapter. source_type="cross_chapter_semantic".

Phase 3e — Summary-Based Cross-Chapter: Claude analyzes chapter summaries to find
structural cross-chapter relationships. source_type="cross_chapter_summary".
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from iconsult_mcp.config import LITERATURE_DIR, BOOK_FILENAME
from iconsult_mcp.db import get_connection
from iconsult_mcp.embed import claude_messages, embed_texts

RELATIONSHIP_TYPES = [
    "uses", "extends", "alternative_to", "component_of",
    "requires", "conflicts_with", "specializes", "precedes",
    "enables", "complements",
]

MAX_CONTEXT_CHARS = 80_000


# --- Utilities ---

def _parse_claude_json(response: str, label: str = "") -> list[dict]:
    """Parse a JSON array from Claude's response, stripping markdown fences."""
    response = response.strip()
    if response.startswith("```"):
        response = re.sub(r"^```(?:json)?\s*", "", response)
        response = re.sub(r"\s*```$", "", response)
    try:
        result = json.loads(response)
        return result if isinstance(result, list) else []
    except json.JSONDecodeError:
        suffix = f" for {label}" if label else ""
        print(f"  Warning: failed to parse Claude JSON response{suffix}")
        return []


def is_done(label: str) -> bool:
    """Check if a sub-phase is already complete."""
    conn = get_connection()
    result = conn.execute(
        "SELECT value FROM pipeline_metadata WHERE key = ?",
        [f"phase3_{label}"],
    ).fetchone()
    return result is not None and result[0] == "true"


def mark_done(label: str):
    """Mark a sub-phase as complete."""
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO pipeline_metadata (key, value) VALUES (?, 'true')",
        [f"phase3_{label}"],
    )


# --- Core helpers ---

def get_chapter_sections_with_text(chapter_number: int, book_lines: list[str]) -> list[dict]:
    """Get sections for a chapter with their text content."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT id, title, line_start, line_end
        FROM sections WHERE chapter_number = ?
        ORDER BY line_start
    """, [chapter_number]).fetchall()

    sections = []
    for r in rows:
        text = "\n".join(book_lines[r[2] - 1 : r[3]])
        # Light cleanup
        text = re.sub(r"\\begin\{figure\}.*?\\end\{figure\}", "[figure]", text, flags=re.DOTALL)
        text = re.sub(r"\\begin\{lstlisting\}.*?\\end\{lstlisting\}", "[code]", text, flags=re.DOTALL)
        text = re.sub(r"!\[.*?\]\(.*?\)", "[image]", text)
        sections.append({"id": r[0], "title": r[1], "text": text})
    return sections


def get_concepts_in_chapter(chapter_number: int) -> list[dict]:
    """Get concepts that appear in a chapter's sections."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT DISTINCT c.id, c.name
        FROM concepts c
        JOIN concept_sections cs ON c.id = cs.concept_id
        JOIN sections s ON cs.section_id = s.id
        WHERE s.chapter_number = ?
        ORDER BY c.name
    """, [chapter_number]).fetchall()
    return [{"id": r[0], "name": r[1]} for r in rows]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def insert_relationships(relationships: list[dict]) -> int:
    """Insert discovered relationships into the database.

    Validates concept IDs against DB, checks for duplicates, and logs failures.
    """
    conn = get_connection()
    valid_concepts = {r[0] for r in conn.execute("SELECT id FROM concepts").fetchall()}

    inserted = 0
    skipped_concept = 0
    skipped_type = 0
    duplicates = 0
    errors = 0

    for r in relationships:
        rel_type = r.get("relationship_type", "")
        fid = r.get("from_concept_id", "")
        tid = r.get("to_concept_id", "")

        if rel_type not in RELATIONSHIP_TYPES:
            skipped_type += 1
            continue
        if fid not in valid_concepts:
            skipped_concept += 1
            continue
        if tid not in valid_concepts:
            skipped_concept += 1
            continue

        # Check for existing duplicate
        existing = conn.execute(
            "SELECT id FROM relationships WHERE from_concept_id = ? AND to_concept_id = ? AND relationship_type = ?",
            [fid, tid, rel_type],
        ).fetchone()
        if existing:
            duplicates += 1
            continue

        provenance_section = r.get("provenance_section")
        provenance_sections = r.get("provenance_sections")
        if provenance_sections is None:
            provenance_sections = [provenance_section] if provenance_section else []

        try:
            conn.execute("""
                INSERT INTO relationships
                (from_concept_id, to_concept_id, relationship_type, confidence,
                 source_type, provenance_sections, provenance_pages, description)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                fid, tid, rel_type,
                r.get("confidence", 0.5),
                r.get("source_type", "explicit"),
                provenance_sections,
                r.get("provenance_pages", []),
                r.get("description", ""),
            ])
            inserted += 1
        except Exception as e:
            errors += 1
            print(f"  ERROR inserting {fid}->{tid} ({rel_type}): {e}")

    if skipped_concept:
        print(f"    Skipped {skipped_concept} with invalid concept IDs")
    if skipped_type:
        print(f"    Skipped {skipped_type} with invalid relationship types")
    if duplicates:
        print(f"    Skipped {duplicates} duplicates")
    if errors:
        print(f"    {errors} insertion errors")

    return inserted


# --- Phase 3a: Explicit relationships ---

async def discover_explicit_relationships(chapter_number: int, book_lines: list[str]) -> list[dict]:
    """Phase 3a: Use Claude to find explicitly stated relationships in a chapter."""
    sections = get_chapter_sections_with_text(chapter_number, book_lines)
    concepts = get_concepts_in_chapter(chapter_number)

    if not sections or not concepts:
        return []

    # Build context with 8K per-section limit
    context = ""
    total_chars = 0
    for s in sections:
        chunk = f"\n\n--- {s['title']} ---\n{s['text'][:8000]}"
        if total_chars + len(chunk) > MAX_CONTEXT_CHARS:
            break
        context += chunk
        total_chars += len(chunk)

    concept_list = "\n".join(f"- {c['name']} (id: {c['id']})" for c in concepts)

    prompt = f"""Analyze the following text from Chapter {chapter_number} of "Agentic Architectural Patterns for Building Multi-Agent Systems".

Identify EXPLICIT relationships between concepts that the authors state or strongly imply. Only include relationships where the text provides evidence.

Concepts in this chapter:
{concept_list}

Text:
{context}

Valid relationship types: {', '.join(RELATIONSHIP_TYPES)}

For each relationship found, provide:
- from_concept_id: source concept ID
- to_concept_id: target concept ID
- relationship_type: one of the valid types above
- confidence: 0.7-1.0 (how clearly the text states this relationship)
- description: one-sentence description of the relationship
- provenance_section: the section ID where this relationship is evidenced

Return ONLY a JSON array:
```json
[
  {{"from_concept_id": "agent_router_pattern", "to_concept_id": "supervisor_architecture", "relationship_type": "alternative_to", "confidence": 0.85, "description": "The Agent Router pattern provides intent-based routing as an alternative to centralized Supervisor Architecture.", "provenance_section": "ch05_the_agent_router_pattern"}}
]
```

Return ONLY the JSON array. If no relationships are found, return []."""

    response = await claude_messages(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=8192,
    )

    results = _parse_claude_json(response, f"chapter {chapter_number}")
    for r in results:
        r["source_type"] = "explicit"
    return results


# --- Phase 3b: Semantic relationships ---

async def discover_semantic_relationships(concepts: list[dict]) -> list[dict]:
    """Phase 3b: Find semantic relationships via embedding similarity.

    1. Embed all concepts
    2. Compute pairwise cosine similarity
    3. For high-similarity pairs, ask Claude to validate (batched in groups of 40)
    """
    if len(concepts) < 2:
        return []

    # Embed concept names + definitions
    texts = []
    for c in concepts:
        text = c["name"]
        if c.get("definition"):
            text += f": {c['definition']}"
        texts.append(text)

    print(f"  Embedding {len(texts)} concepts...")
    embeddings = await embed_texts(texts)

    # Store embeddings for later use
    conn = get_connection()
    for c, emb, text in zip(concepts, embeddings, texts):
        try:
            conn.execute("""
                INSERT OR REPLACE INTO concept_embeddings (concept_id, embedding, embedded_text)
                VALUES (?, ?, ?)
            """, [c["id"], emb, text])
        except Exception as e:
            print(f"  Warning: failed to store embedding for {c['id']}: {e}")

    # Compute pairwise similarities
    print("  Computing pairwise similarities...")
    pairs = []
    for i in range(len(concepts)):
        for j in range(i + 1, len(concepts)):
            sim = _cosine_similarity(embeddings[i], embeddings[j])
            if sim >= 0.5:  # Only consider moderately similar pairs
                pairs.append((concepts[i], concepts[j], sim))

    pairs.sort(key=lambda x: x[2], reverse=True)
    pairs = pairs[:300]  # Raised from 50

    if not pairs:
        print("  No high-similarity pairs found")
        return []

    print(f"  Validating {len(pairs)} high-similarity concept pairs with Claude...")

    # Batch pairs in groups of 40 for Claude validation
    all_results = []
    batch_size = 40
    for batch_start in range(0, len(pairs), batch_size):
        batch = pairs[batch_start:batch_start + batch_size]
        batch_num = batch_start // batch_size + 1
        total_batches = (len(pairs) + batch_size - 1) // batch_size
        print(f"    Batch {batch_num}/{total_batches} ({len(batch)} pairs)...")

        pair_descriptions = "\n".join(
            f"- {p[0]['name']} <-> {p[1]['name']} (similarity: {p[2]:.3f})"
            for p in batch
        )
        pair_ids = "\n".join(
            f"- {p[0]['id']} <-> {p[1]['id']}"
            for p in batch
        )

        prompt = f"""Given these pairs of concepts from "Agentic Architectural Patterns for Building Multi-Agent Systems" that have high semantic similarity, determine if there is a meaningful architectural relationship between them.

Concept pairs (with cosine similarity):
{pair_descriptions}

Concept IDs:
{pair_ids}

Valid relationship types: {', '.join(RELATIONSHIP_TYPES)}

For each pair where a real relationship exists, provide:
- from_concept_id / to_concept_id
- relationship_type
- confidence: 0.3-0.7 (these are inferred, not explicitly stated)
- description: one-sentence description

Return ONLY a JSON array. Skip pairs that are:
- Duplicate/variant names for the same concept
- Only superficially similar with no real architectural relationship
```json
[
  {{"from_concept_id": "...", "to_concept_id": "...", "relationship_type": "...", "confidence": 0.5, "description": "..."}}
]
```"""

        response = await claude_messages(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=8192,
        )

        batch_results = _parse_claude_json(response, f"semantic batch {batch_num}")
        for r in batch_results:
            r["source_type"] = "semantic"
        all_results.extend(batch_results)

    return all_results


# --- Phase 3c: Cross-Chapter Knowledge-Based ---

async def discover_cross_chapter_knowledge(concepts: list[dict]) -> list[dict]:
    """Phase 3c: Claude identifies cross-chapter relationships using domain knowledge.

    Sends all concepts with definitions in overlapping batches sorted by category.
    No book text is used — purely knowledge-based inference.
    """
    if len(concepts) < 2:
        return []

    # Sort by category for coherent groupings
    concepts_sorted = sorted(concepts, key=lambda c: (c.get("category") or "", c["name"]))

    # Create overlapping batches of ~35, overlapping by 5
    batch_size = 35
    overlap = 5
    batches = []
    i = 0
    while i < len(concepts_sorted):
        end = min(i + batch_size, len(concepts_sorted))
        batches.append(concepts_sorted[i:end])
        if end == len(concepts_sorted):
            break
        i += batch_size - overlap

    print(f"  Processing {len(batches)} concept batches...")
    all_results = []

    for batch_idx, batch in enumerate(batches):
        print(f"    Batch {batch_idx + 1}/{len(batches)} ({len(batch)} concepts)...")

        concept_list = "\n".join(
            f"- {c['name']} (id: {c['id']}){': ' + c['definition'] if c.get('definition') else ''}"
            for c in batch
        )

        prompt = f"""You are an expert in multi-agent systems and software architecture patterns.

Below are concepts from the book "Agentic Architectural Patterns for Building Multi-Agent Systems". Using your domain knowledge and the provided definitions, identify meaningful relationships between these concepts.

Focus on relationships that cross different areas of the architecture — connections between patterns, between infrastructure and patterns, between evaluation methods and patterns, etc.

Concepts:
{concept_list}

Valid relationship types: {', '.join(RELATIONSHIP_TYPES)}

For each relationship, provide:
- from_concept_id / to_concept_id
- relationship_type: one of the valid types
- confidence: 0.5-0.8 (knowledge-based inference)
- description: one-sentence description of the relationship

Return ONLY a JSON array. Be selective — only include relationships you are confident about:
```json
[
  {{"from_concept_id": "...", "to_concept_id": "...", "relationship_type": "...", "confidence": 0.6, "description": "..."}}
]
```"""

        response = await claude_messages(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=8192,
        )

        batch_results = _parse_claude_json(response, f"cross-chapter knowledge batch {batch_idx + 1}")
        for r in batch_results:
            r["source_type"] = "cross_chapter_knowledge"
        all_results.extend(batch_results)

    return all_results


# --- Phase 3d: Cross-Chapter Semantic Pairs ---

async def discover_cross_chapter_semantic(concepts: list[dict]) -> list[dict]:
    """Phase 3d: Embedding-based discovery of cross-chapter relationships.

    Identifies concept pairs that never co-occurred in the same chapter during
    Phase 3a, ranks by embedding similarity, and validates with Claude.
    """
    conn = get_connection()

    # Find which chapters each concept appears in
    chapter_map: dict[str, set[int]] = {}
    rows = conn.execute("""
        SELECT DISTINCT cs.concept_id, s.chapter_number
        FROM concept_sections cs
        JOIN sections s ON cs.section_id = s.id
    """).fetchall()
    for concept_id, ch_num in rows:
        if concept_id not in chapter_map:
            chapter_map[concept_id] = set()
        chapter_map[concept_id].add(ch_num)

    # Load cached embeddings
    emb_rows = conn.execute("""
        SELECT concept_id, embedding FROM concept_embeddings
    """).fetchall()
    embeddings_map = {r[0]: r[1] for r in emb_rows}

    if not embeddings_map:
        print("  No cached embeddings found — run Phase 3b first")
        return []

    # Build concept lookup
    concept_lookup = {c["id"]: c for c in concepts}

    # Find cross-chapter pairs (never in same chapter)
    concept_ids = [c["id"] for c in concepts if c["id"] in embeddings_map]
    cross_pairs = []
    for i in range(len(concept_ids)):
        for j in range(i + 1, len(concept_ids)):
            cid_a = concept_ids[i]
            cid_b = concept_ids[j]
            chapters_a = chapter_map.get(cid_a, set())
            chapters_b = chapter_map.get(cid_b, set())
            # Skip if they share a chapter (already covered by Phase 3a)
            if chapters_a & chapters_b:
                continue
            # Compute similarity
            sim = _cosine_similarity(embeddings_map[cid_a], embeddings_map[cid_b])
            if sim >= 0.3:  # Lower threshold for cross-chapter
                cross_pairs.append((cid_a, cid_b, sim))

    cross_pairs.sort(key=lambda x: x[2], reverse=True)
    cross_pairs = cross_pairs[:400]

    if not cross_pairs:
        print("  No cross-chapter semantic pairs found")
        return []

    print(f"  Validating {len(cross_pairs)} cross-chapter pairs with Claude...")

    # Get section titles for context
    section_titles: dict[str, list[str]] = {}
    for cid in concept_ids:
        titles = conn.execute("""
            SELECT s.title FROM concept_sections cs
            JOIN sections s ON cs.section_id = s.id
            WHERE cs.concept_id = ?
            ORDER BY cs.confidence DESC
            LIMIT 3
        """, [cid]).fetchall()
        section_titles[cid] = [t[0] for t in titles]

    # Batch pairs in groups of 40
    all_results = []
    batch_size = 40
    for batch_start in range(0, len(cross_pairs), batch_size):
        batch = cross_pairs[batch_start:batch_start + batch_size]
        batch_num = batch_start // batch_size + 1
        total_batches = (len(cross_pairs) + batch_size - 1) // batch_size
        print(f"    Batch {batch_num}/{total_batches} ({len(batch)} pairs)...")

        pair_descriptions = []
        for cid_a, cid_b, sim in batch:
            ca = concept_lookup.get(cid_a, {})
            cb = concept_lookup.get(cid_b, {})
            name_a = ca.get("name", cid_a)
            name_b = cb.get("name", cid_b)
            def_a = ca.get("definition", "")
            def_b = cb.get("definition", "")
            sections_a = ", ".join(section_titles.get(cid_a, []))
            sections_b = ", ".join(section_titles.get(cid_b, []))

            desc = f"- {name_a} (id: {cid_a})"
            if def_a:
                desc += f"\n  Definition: {def_a}"
            if sections_a:
                desc += f"\n  Sections: {sections_a}"
            desc += f"\n  <-> {name_b} (id: {cid_b})"
            if def_b:
                desc += f"\n  Definition: {def_b}"
            if sections_b:
                desc += f"\n  Sections: {sections_b}"
            desc += f"\n  Similarity: {sim:.3f}"
            pair_descriptions.append(desc)

        pairs_text = "\n\n".join(pair_descriptions)

        prompt = f"""These concept pairs are from DIFFERENT chapters of "Agentic Architectural Patterns for Building Multi-Agent Systems" and have never been analyzed together. They have semantic similarity but may or may not have a real architectural relationship.

For each pair, determine if there is a meaningful cross-chapter relationship.

Concept pairs:
{pairs_text}

Valid relationship types: {', '.join(RELATIONSHIP_TYPES)}

For each pair where a real relationship exists, provide:
- from_concept_id / to_concept_id
- relationship_type
- confidence: 0.3-0.7 (cross-chapter inferred relationships)
- description: one-sentence description

Return ONLY a JSON array. Be selective — skip pairs with only superficial similarity:
```json
[
  {{"from_concept_id": "...", "to_concept_id": "...", "relationship_type": "...", "confidence": 0.5, "description": "..."}}
]
```"""

        response = await claude_messages(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=8192,
        )

        batch_results = _parse_claude_json(response, f"cross-chapter semantic batch {batch_num}")
        for r in batch_results:
            r["source_type"] = "cross_chapter_semantic"
        all_results.extend(batch_results)

    return all_results


# --- Phase 3e: Summary-Based Cross-Chapter ---

async def discover_cross_chapter_summary() -> list[dict]:
    """Phase 3e: Claude analyzes chapter summaries to find structural cross-chapter relationships.

    Collects key concepts, definitions, and existing internal relationships for each chapter,
    then asks Claude to identify structural connections between chapters.
    """
    conn = get_connection()

    # Get all chapters
    chapters = conn.execute(
        "SELECT DISTINCT chapter_number FROM sections ORDER BY chapter_number"
    ).fetchall()

    # Build chapter summaries
    chapter_summaries = []
    for (ch_num,) in chapters:
        # Get concepts in this chapter
        concepts = conn.execute("""
            SELECT DISTINCT c.id, c.name, c.definition
            FROM concepts c
            JOIN concept_sections cs ON c.id = cs.concept_id
            JOIN sections s ON cs.section_id = s.id
            WHERE s.chapter_number = ?
            ORDER BY c.name
        """, [ch_num]).fetchall()

        if not concepts:
            continue

        concept_ids = [c[0] for c in concepts]

        # Get internal relationships for this chapter
        placeholders = ", ".join(["?"] * len(concept_ids))
        rels = conn.execute(f"""
            SELECT r.from_concept_id, r.to_concept_id, r.relationship_type, r.description
            FROM relationships r
            WHERE r.from_concept_id IN ({placeholders})
              AND r.to_concept_id IN ({placeholders})
              AND r.source_type = 'explicit'
            ORDER BY r.confidence DESC
            LIMIT 20
        """, concept_ids + concept_ids).fetchall()

        concept_lines = []
        for c in concepts:
            line = f"  - {c[1]} (id: {c[0]})"
            if c[2]:
                line += f": {c[2][:150]}"
            concept_lines.append(line)

        rel_lines = []
        for r in rels:
            if r[3]:
                rel_lines.append(f"  - {r[0]} --[{r[2]}]--> {r[1]}: {r[3][:100]}")
            else:
                rel_lines.append(f"  - {r[0]} --[{r[2]}]--> {r[1]}")

        summary = f"Chapter {ch_num}:\n"
        summary += f"  Key concepts ({len(concepts)}):\n" + "\n".join(concept_lines)
        if rel_lines:
            summary += f"\n  Internal relationships ({len(rels)}):\n" + "\n".join(rel_lines)

        chapter_summaries.append(summary)

    summaries_text = "\n\n".join(chapter_summaries)

    print(f"  Sending {len(chapter_summaries)} chapter summaries to Claude...")

    prompt = f"""You are analyzing the structure of "Agentic Architectural Patterns for Building Multi-Agent Systems". Below are summaries of each chapter with their key concepts and internal relationships.

Your task: identify CROSS-CHAPTER relationships — meaningful connections between concepts from different chapters that reveal the book's architectural structure.

Focus on:
- Patterns that build on foundations from earlier chapters
- Alternative approaches discussed in different chapters
- Infrastructure concepts that enable patterns in other chapters
- Evaluation methods that apply to specific patterns
- Concepts that complement each other across chapters

{summaries_text}

Valid relationship types: {', '.join(RELATIONSHIP_TYPES)}

For each cross-chapter relationship, provide:
- from_concept_id / to_concept_id (must be from DIFFERENT chapters)
- relationship_type
- confidence: 0.5-0.8
- description: one-sentence description of the structural relationship

Return ONLY a JSON array. Focus on architecturally significant relationships:
```json
[
  {{"from_concept_id": "...", "to_concept_id": "...", "relationship_type": "...", "confidence": 0.7, "description": "..."}}
]
```"""

    response = await claude_messages(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=8192,
    )

    results = _parse_claude_json(response, "cross-chapter summary")
    for r in results:
        r["source_type"] = "cross_chapter_summary"

    print(f"  Got {len(results)} relationships from summary analysis")
    return results


# --- Main orchestrator ---

async def run_phase3(sub_phases: list[str] | None = None):
    """Run Phase 3: discover all relationships.

    Args:
        sub_phases: Optional list of specific sub-phases to run (e.g., ["3c", "3d"]).
                    If None, runs all sub-phases that haven't completed yet.
    """
    conn = get_connection()

    all_subs = ["3a", "3b", "3c", "3d", "3e"]
    to_run = sub_phases if sub_phases else all_subs

    # Shared data (loaded lazily)
    book_lines = None
    concepts = None

    def load_book():
        nonlocal book_lines
        if book_lines is None:
            book_path = LITERATURE_DIR / BOOK_FILENAME
            book_lines = book_path.read_text(encoding="utf-8").splitlines()
        return book_lines

    def load_concepts():
        nonlocal concepts
        if concepts is None:
            rows = conn.execute(
                "SELECT id, name, definition, category FROM concepts ORDER BY name"
            ).fetchall()
            concepts = [{"id": r[0], "name": r[1], "definition": r[2], "category": r[3]} for r in rows]
        return concepts

    # Phase 3a: Explicit relationships
    if "3a" in to_run:
        if is_done("3a_complete"):
            print("Phase 3a already complete. Skipping.")
        else:
            print("=== Phase 3a: Discovering explicit relationships ===")

            # Only clear relationships on fresh 3a run
            existing_count = conn.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
            if existing_count > 0:
                print(f"  Clearing {existing_count} existing relationships for fresh Phase 3a run...")
                conn.execute("DELETE FROM relationships")

            lines = load_book()
            chapters = conn.execute(
                "SELECT DISTINCT chapter_number FROM sections ORDER BY chapter_number"
            ).fetchall()

            all_explicit = []
            for (ch_num,) in chapters:
                print(f"\n  Chapter {ch_num}...")
                rels = await discover_explicit_relationships(ch_num, lines)
                print(f"    Found {len(rels)} explicit relationships")
                all_explicit.extend(rels)

            explicit_count = insert_relationships(all_explicit)
            print(f"\nInserted {explicit_count} explicit relationships")
            mark_done("3a_complete")

    # Phase 3b: Semantic relationships
    if "3b" in to_run:
        if is_done("3b_complete"):
            print("Phase 3b already complete. Skipping.")
        else:
            print("\n=== Phase 3b: Discovering semantic relationships ===")
            concept_dicts = load_concepts()
            semantic_rels = await discover_semantic_relationships(concept_dicts)
            semantic_count = insert_relationships(semantic_rels)
            print(f"Inserted {semantic_count} semantic relationships")
            mark_done("3b_complete")

    # Phase 3c: Cross-chapter knowledge-based
    if "3c" in to_run:
        if is_done("3c_complete"):
            print("Phase 3c already complete. Skipping.")
        else:
            print("\n=== Phase 3c: Cross-chapter knowledge-based relationships ===")
            concept_dicts = load_concepts()
            knowledge_rels = await discover_cross_chapter_knowledge(concept_dicts)
            knowledge_count = insert_relationships(knowledge_rels)
            print(f"Inserted {knowledge_count} cross-chapter knowledge relationships")
            mark_done("3c_complete")

    # Phase 3d: Cross-chapter semantic pairs
    if "3d" in to_run:
        if is_done("3d_complete"):
            print("Phase 3d already complete. Skipping.")
        else:
            print("\n=== Phase 3d: Cross-chapter semantic relationships ===")
            concept_dicts = load_concepts()
            cross_sem_rels = await discover_cross_chapter_semantic(concept_dicts)
            cross_sem_count = insert_relationships(cross_sem_rels)
            print(f"Inserted {cross_sem_count} cross-chapter semantic relationships")
            mark_done("3d_complete")

    # Phase 3e: Summary-based cross-chapter
    if "3e" in to_run:
        if is_done("3e_complete"):
            print("Phase 3e already complete. Skipping.")
        else:
            print("\n=== Phase 3e: Summary-based cross-chapter relationships ===")
            summary_rels = await discover_cross_chapter_summary()
            summary_count = insert_relationships(summary_rels)
            print(f"Inserted {summary_count} summary-based cross-chapter relationships")
            mark_done("3e_complete")

    # Mark overall phase3 as complete if all sub-phases are done
    all_done = all(is_done(f"{s}_complete") for s in all_subs)
    if all_done:
        conn.execute("""
            INSERT OR REPLACE INTO pipeline_metadata (key, value)
            VALUES ('phase3_complete', 'true')
        """)

    total = conn.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
    print(f"\nTotal relationships: {total}")

    # Source type breakdown
    breakdown = conn.execute(
        "SELECT source_type, COUNT(*) FROM relationships GROUP BY source_type ORDER BY COUNT(*) DESC"
    ).fetchall()
    for source, count in breakdown:
        print(f"  {source}: {count}")


def main():
    import asyncio
    asyncio.run(run_phase3())


if __name__ == "__main__":
    main()
