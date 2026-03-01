"""
Phase 4: Build and validate the final knowledge graph.

- Deduplicate relationships
- Remove very low confidence edges
- Generate section embeddings
- Validate graph integrity
- Write stats to pipeline_metadata
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from iconsult_mcp.db import get_connection, get_stats
from iconsult_mcp.embed import embed_texts

MIN_CONFIDENCE = 0.3


async def deduplicate_relationships():
    """Remove duplicate relationships (same concept pair + type, keep highest confidence)."""
    conn = get_connection()

    # Find duplicates
    dupes = conn.execute("""
        SELECT from_concept_id, to_concept_id, relationship_type, COUNT(*) as cnt
        FROM relationships
        GROUP BY from_concept_id, to_concept_id, relationship_type
        HAVING cnt > 1
    """).fetchall()

    removed = 0
    for from_id, to_id, rel_type, count in dupes:
        # Keep the one with highest confidence, delete the rest
        rows = conn.execute("""
            SELECT id, confidence FROM relationships
            WHERE from_concept_id = ? AND to_concept_id = ? AND relationship_type = ?
            ORDER BY confidence DESC
        """, [from_id, to_id, rel_type]).fetchall()

        # Delete all except the first (highest confidence)
        for row_id, _ in rows[1:]:
            conn.execute("DELETE FROM relationships WHERE id = ?", [row_id])
            removed += 1

    print(f"  Removed {removed} duplicate relationships")
    return removed


async def remove_low_confidence():
    """Remove relationships below the minimum confidence threshold."""
    conn = get_connection()

    result = conn.execute(
        "SELECT COUNT(*) FROM relationships WHERE confidence < ?",
        [MIN_CONFIDENCE],
    ).fetchone()
    count = result[0]

    if count > 0:
        conn.execute(
            "DELETE FROM relationships WHERE confidence < ?",
            [MIN_CONFIDENCE],
        )
        print(f"  Removed {count} low-confidence relationships (< {MIN_CONFIDENCE})")
    else:
        print("  No low-confidence relationships to remove")

    return count


async def generate_concept_embeddings():
    """Generate embeddings for concepts that don't have them yet."""
    conn = get_connection()

    rows = conn.execute("""
        SELECT c.id, c.name, c.definition
        FROM concepts c
        LEFT JOIN concept_embeddings ce ON c.id = ce.concept_id
        WHERE ce.concept_id IS NULL
    """).fetchall()

    if not rows:
        print("  All concepts already have embeddings")
        return 0

    ids = [r[0] for r in rows]
    texts = []
    for r in rows:
        text = r[1]  # name
        if r[2]:  # definition
            text += f": {r[2]}"
        texts.append(text)

    print(f"  Embedding {len(texts)} concepts...")
    embeddings = await embed_texts(texts)

    for cid, emb, text in zip(ids, embeddings, texts):
        try:
            conn.execute("""
                INSERT OR REPLACE INTO concept_embeddings (concept_id, embedding, embedded_text)
                VALUES (?, ?, ?)
            """, [cid, emb, text])
        except Exception:
            pass

    print(f"  Generated {len(embeddings)} concept embeddings")
    return len(embeddings)


async def generate_section_embeddings():
    """Generate embeddings for sections using title + content.

    Deletes existing section embeddings first so they get regenerated
    with real book content instead of title-only.
    """
    conn = get_connection()

    # Delete existing embeddings so all sections get re-embedded with content
    conn.execute("DELETE FROM section_embeddings")
    print("  Cleared existing section embeddings for re-generation")

    rows = conn.execute("""
        SELECT s.id, s.title, s.content
        FROM sections s
    """).fetchall()

    if not rows:
        print("  No sections found")
        return 0

    # Build embedding texts: title + truncated content (~3000 tokens ≈ 2300 words)
    MAX_CONTENT_WORDS = 2300
    ids = [r[0] for r in rows]
    texts = []
    for r in rows:
        text = r[1]  # title
        if r[2]:  # content
            words = r[2].split()
            truncated = " ".join(words[:MAX_CONTENT_WORDS])
            text += ": " + truncated
        texts.append(text)

    print(f"  Embedding {len(texts)} sections in chunks...")

    # Process in chunks of 30, saving to DB after each chunk
    chunk_size = 30
    total_embedded = 0
    for i in range(0, len(texts), chunk_size):
        chunk_ids = ids[i:i + chunk_size]
        chunk_texts = texts[i:i + chunk_size]

        try:
            chunk_embeddings = await embed_texts(chunk_texts)
        except Exception as e:
            print(f"  Warning: failed to embed chunk {i // chunk_size + 1}: {e}")
            continue

        for sid, emb, text in zip(chunk_ids, chunk_embeddings, chunk_texts):
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO section_embeddings (section_id, embedding, embedded_text)
                    VALUES (?, ?, ?)
                """, [sid, emb, text])
                total_embedded += 1
            except Exception:
                pass

        print(f"  Chunk {i // chunk_size + 1}/{(len(texts) + chunk_size - 1) // chunk_size}: {total_embedded} embedded so far")

    print(f"  Generated {total_embedded} section embeddings")
    return total_embedded


async def validate_graph():
    """Validate graph integrity and report issues."""
    conn = get_connection()
    issues = []

    # Check for orphan relationships (referencing non-existent concepts)
    orphans = conn.execute("""
        SELECT r.id, r.from_concept_id, r.to_concept_id
        FROM relationships r
        LEFT JOIN concepts cf ON r.from_concept_id = cf.id
        LEFT JOIN concepts ct ON r.to_concept_id = ct.id
        WHERE cf.id IS NULL OR ct.id IS NULL
    """).fetchall()

    if orphans:
        issues.append(f"Found {len(orphans)} relationships referencing non-existent concepts")
        # Clean up orphans
        for r_id, _, _ in orphans:
            conn.execute("DELETE FROM relationships WHERE id = ?", [r_id])
        print(f"  Removed {len(orphans)} orphan relationships")

    # Check for concept_sections referencing non-existent entities
    orphan_cs = conn.execute("""
        SELECT cs.concept_id, cs.section_id
        FROM concept_sections cs
        LEFT JOIN concepts c ON cs.concept_id = c.id
        LEFT JOIN sections s ON cs.section_id = s.id
        WHERE c.id IS NULL OR s.id IS NULL
    """).fetchall()

    if orphan_cs:
        issues.append(f"Found {len(orphan_cs)} concept_sections with invalid references")
        conn.execute("""
            DELETE FROM concept_sections
            WHERE concept_id NOT IN (SELECT id FROM concepts)
               OR section_id NOT IN (SELECT id FROM sections)
        """)
        print(f"  Cleaned up {len(orphan_cs)} invalid concept_section mappings")

    # Check concepts without any relationships
    isolated = conn.execute("""
        SELECT COUNT(*) FROM concepts c
        WHERE c.id NOT IN (
            SELECT from_concept_id FROM relationships
            UNION
            SELECT to_concept_id FROM relationships
        )
    """).fetchone()[0]

    if isolated > 0:
        issues.append(f"{isolated} concepts have no relationships (isolated nodes)")
        print(f"  Note: {isolated} concepts are isolated (no relationships)")

    # Concepts without definitions
    no_def = conn.execute(
        "SELECT COUNT(*) FROM concepts WHERE definition IS NULL"
    ).fetchone()[0]
    if no_def > 0:
        issues.append(f"{no_def} concepts have no definition")
        print(f"  Note: {no_def} concepts lack definitions")

    return issues


async def write_final_stats():
    """Write final graph statistics to pipeline_metadata."""
    conn = get_connection()
    stats = get_stats()

    for key, value in [
        ("final_concept_count", str(stats["concepts"])),
        ("final_section_count", str(stats["sections"])),
        ("final_relationship_count", str(stats["relationships"])),
        ("final_avg_confidence", str(stats["avg_relationship_confidence"])),
    ]:
        conn.execute("""
            INSERT OR REPLACE INTO pipeline_metadata (key, value)
            VALUES (?, ?)
        """, [key, value])

    return stats


async def run_phase4():
    """Run Phase 4: build and validate final graph."""
    conn = get_connection()

    existing = conn.execute(
        "SELECT value FROM pipeline_metadata WHERE key = 'phase4_complete'"
    ).fetchone()
    if existing and existing[0] == "true":
        print("Phase 4 already complete. Skipping.")
        return

    print("=== Phase 4: Building final knowledge graph ===")

    print("\n1. Deduplicating relationships...")
    await deduplicate_relationships()

    print("\n2. Removing low-confidence edges...")
    await remove_low_confidence()

    print("\n3. Generating concept embeddings...")
    await generate_concept_embeddings()

    print("\n4. Generating section embeddings...")
    await generate_section_embeddings()

    print("\n5. Validating graph integrity...")
    issues = await validate_graph()

    print("\n6. Writing final statistics...")
    stats = await write_final_stats()

    conn.execute("""
        INSERT OR REPLACE INTO pipeline_metadata (key, value)
        VALUES ('phase4_complete', 'true')
    """)

    print("\n=== Final Graph Statistics ===")
    print(f"  Concepts: {stats['concepts']}")
    print(f"  Sections: {stats['sections']}")
    print(f"  Relationships: {stats['relationships']}")
    print(f"  Avg confidence: {stats['avg_relationship_confidence']}")
    if stats.get("relationship_types"):
        print("  Relationship types:")
        for rt, count in stats["relationship_types"].items():
            print(f"    {rt}: {count}")
    if issues:
        print(f"  Validation issues: {len(issues)}")
        for issue in issues:
            print(f"    - {issue}")


def main():
    import asyncio
    asyncio.run(run_phase4())


if __name__ == "__main__":
    main()
