"""
Phase 4: Build and validate the final knowledge graph (book-scoped).

- Deduplicate relationships
- Remove very low confidence edges
- Generate section embeddings
- Validate graph integrity
- Write stats to pipeline_metadata
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from iconsult_mcp.db import get_connection, get_stats
from iconsult_mcp.embed import embed_texts

DEFAULT_BOOK_ID = "arsanjani_2026"
MIN_CONFIDENCE = 0.3


async def deduplicate_relationships(book_id: str):
    """Remove duplicate relationships for one book (keep highest confidence)."""
    conn = get_connection()

    dupes = conn.execute("""
        SELECT from_concept_id, to_concept_id, relationship_type, COUNT(*) as cnt
        FROM relationships
        WHERE book_id = ?
        GROUP BY from_concept_id, to_concept_id, relationship_type
        HAVING cnt > 1
    """, [book_id]).fetchall()

    removed = 0
    for from_id, to_id, rel_type, count in dupes:
        rows = conn.execute("""
            SELECT id, confidence FROM relationships
            WHERE from_concept_id = ? AND to_concept_id = ?
              AND relationship_type = ? AND book_id = ?
            ORDER BY confidence DESC
        """, [from_id, to_id, rel_type, book_id]).fetchall()

        for row_id, _ in rows[1:]:
            conn.execute("DELETE FROM relationships WHERE id = ?", [row_id])
            removed += 1

    print(f"  Removed {removed} duplicate relationships")
    return removed


async def remove_low_confidence(book_id: str):
    """Remove relationships below the minimum confidence threshold (book-scoped)."""
    conn = get_connection()

    count = conn.execute(
        "SELECT COUNT(*) FROM relationships WHERE confidence < ? AND book_id = ?",
        [MIN_CONFIDENCE, book_id],
    ).fetchone()[0]

    if count > 0:
        conn.execute(
            "DELETE FROM relationships WHERE confidence < ? AND book_id = ?",
            [MIN_CONFIDENCE, book_id],
        )
        print(f"  Removed {count} low-confidence relationships (< {MIN_CONFIDENCE})")
    else:
        print("  No low-confidence relationships to remove")

    return count


async def generate_concept_embeddings(book_id: str):
    """Generate embeddings for this book's concepts that don't have them yet."""
    conn = get_connection()

    rows = conn.execute("""
        SELECT c.id, c.name, c.definition
        FROM concepts c
        LEFT JOIN concept_embeddings ce ON c.id = ce.concept_id
        WHERE ce.concept_id IS NULL AND c.book_id = ?
    """, [book_id]).fetchall()

    if not rows:
        print("  All concepts already have embeddings")
        return 0

    ids = [r[0] for r in rows]
    texts = []
    for r in rows:
        text = r[1]
        if r[2]:
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


async def generate_section_embeddings(book_id: str):
    """Re-embed this book's sections using title + truncated content."""
    conn = get_connection()

    # Delete only this book's section embeddings (join via sections.book_id)
    conn.execute("""
        DELETE FROM section_embeddings
        WHERE section_id IN (SELECT id FROM sections WHERE book_id = ?)
    """, [book_id])
    print(f"  Cleared existing section embeddings for {book_id}")

    rows = conn.execute(
        "SELECT s.id, s.title, s.content FROM sections s WHERE s.book_id = ?",
        [book_id],
    ).fetchall()

    if not rows:
        print("  No sections found")
        return 0

    MAX_CONTENT_WORDS = 2300
    ids = [r[0] for r in rows]
    texts = []
    for r in rows:
        text = r[1]
        if r[2]:
            words = r[2].split()
            truncated = " ".join(words[:MAX_CONTENT_WORDS])
            text += ": " + truncated
        texts.append(text)

    print(f"  Embedding {len(texts)} sections in chunks...")

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


async def validate_graph(book_id: str):
    """Validate this book's graph integrity and report issues."""
    conn = get_connection()
    issues = []

    # Orphan relationships within this book
    orphans = conn.execute("""
        SELECT r.id, r.from_concept_id, r.to_concept_id
        FROM relationships r
        LEFT JOIN concepts cf ON r.from_concept_id = cf.id
        LEFT JOIN concepts ct ON r.to_concept_id = ct.id
        WHERE r.book_id = ? AND (cf.id IS NULL OR ct.id IS NULL)
    """, [book_id]).fetchall()

    if orphans:
        issues.append(f"Found {len(orphans)} relationships referencing non-existent concepts")
        for r_id, _, _ in orphans:
            conn.execute("DELETE FROM relationships WHERE id = ?", [r_id])
        print(f"  Removed {len(orphans)} orphan relationships")

    # Orphan concept_sections (scoped via concepts.book_id join)
    orphan_cs = conn.execute("""
        SELECT cs.concept_id, cs.section_id
        FROM concept_sections cs
        JOIN concepts c ON cs.concept_id = c.id
        LEFT JOIN sections s ON cs.section_id = s.id
        WHERE c.book_id = ? AND s.id IS NULL
    """, [book_id]).fetchall()

    if orphan_cs:
        issues.append(f"Found {len(orphan_cs)} concept_sections with invalid section references")
        conn.execute("""
            DELETE FROM concept_sections
            WHERE concept_id IN (SELECT id FROM concepts WHERE book_id = ?)
              AND section_id NOT IN (SELECT id FROM sections)
        """, [book_id])
        print(f"  Cleaned up {len(orphan_cs)} invalid concept_section mappings")

    # Isolated concepts within this book
    isolated = conn.execute("""
        SELECT COUNT(*) FROM concepts c
        WHERE c.book_id = ?
          AND c.id NOT IN (
            SELECT from_concept_id FROM relationships WHERE book_id = ?
            UNION
            SELECT to_concept_id FROM relationships WHERE book_id = ?
          )
    """, [book_id, book_id, book_id]).fetchone()[0]

    if isolated > 0:
        issues.append(f"{isolated} concepts have no relationships (isolated nodes)")
        print(f"  Note: {isolated} concepts are isolated (no relationships)")

    no_def = conn.execute(
        "SELECT COUNT(*) FROM concepts WHERE definition IS NULL AND book_id = ?",
        [book_id],
    ).fetchone()[0]
    if no_def > 0:
        issues.append(f"{no_def} concepts have no definition")
        print(f"  Note: {no_def} concepts lack definitions")

    return issues


async def write_final_stats(book_id: str):
    """Write final graph statistics for this book to pipeline_metadata."""
    conn = get_connection()
    # Note: get_stats() returns global stats; for per-book stats we re-compute
    concept_count = conn.execute(
        "SELECT COUNT(*) FROM concepts WHERE book_id = ?", [book_id]
    ).fetchone()[0]
    section_count = conn.execute(
        "SELECT COUNT(*) FROM sections WHERE book_id = ?", [book_id]
    ).fetchone()[0]
    rel_count = conn.execute(
        "SELECT COUNT(*) FROM relationships WHERE book_id = ?", [book_id]
    ).fetchone()[0]
    avg_conf = conn.execute(
        "SELECT ROUND(AVG(confidence), 3) FROM relationships WHERE book_id = ?",
        [book_id],
    ).fetchone()[0]

    for key_suffix, value in [
        ("final_concept_count", str(concept_count)),
        ("final_section_count", str(section_count)),
        ("final_relationship_count", str(rel_count)),
        ("final_avg_confidence", str(avg_conf)),
    ]:
        conn.execute(
            "INSERT OR REPLACE INTO pipeline_metadata (key, value) VALUES (?, ?)",
            [f"{key_suffix}:{book_id}", value],
        )

    return {
        "concepts": concept_count,
        "sections": section_count,
        "relationships": rel_count,
        "avg_relationship_confidence": avg_conf,
    }


async def run_phase4(book_id: str):
    """Run Phase 4 for one book: build and validate final graph."""
    conn = get_connection()

    metadata_key = f"phase4_complete:{book_id}"
    existing = conn.execute(
        "SELECT value FROM pipeline_metadata WHERE key = ?", [metadata_key]
    ).fetchone()
    if existing and existing[0] == "true":
        print(f"Phase 4 already complete for {book_id}. Skipping.")
        return

    print(f"=== Phase 4: Building final knowledge graph for {book_id} ===")

    print("\n1. Deduplicating relationships...")
    await deduplicate_relationships(book_id)

    print("\n2. Removing low-confidence edges...")
    await remove_low_confidence(book_id)

    print("\n3. Generating concept embeddings...")
    await generate_concept_embeddings(book_id)

    print("\n4. Generating section embeddings...")
    await generate_section_embeddings(book_id)

    print("\n5. Validating graph integrity...")
    issues = await validate_graph(book_id)

    print("\n6. Writing final statistics...")
    stats = await write_final_stats(book_id)

    conn.execute(
        "INSERT OR REPLACE INTO pipeline_metadata (key, value) VALUES (?, 'true')",
        [metadata_key],
    )

    print(f"\n=== Final Graph Statistics for {book_id} ===")
    print(f"  Concepts: {stats['concepts']}")
    print(f"  Sections: {stats['sections']}")
    print(f"  Relationships: {stats['relationships']}")
    print(f"  Avg confidence: {stats['avg_relationship_confidence']}")
    if issues:
        print(f"  Validation issues: {len(issues)}")
        for issue in issues:
            print(f"    - {issue}")


def main():
    parser = argparse.ArgumentParser(description="Build and validate the final knowledge graph for one book.")
    parser.add_argument(
        "--book",
        default=DEFAULT_BOOK_ID,
        help=f"Book ID from config.BOOKS (default: {DEFAULT_BOOK_ID}).",
    )
    args = parser.parse_args()

    import asyncio
    asyncio.run(run_phase4(args.book))


if __name__ == "__main__":
    main()
