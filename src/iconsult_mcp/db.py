"""
DuckDB/MotherDuck database module for the knowledge graph.

Handles connection management (singleton) and schema initialization
for all knowledge graph tables.
"""

import logging
from typing import Optional

import duckdb

from iconsult_mcp.config import (
    EMBEDDING_DIMENSIONS,
    MOTHERDUCK_DATABASE,
    MOTHERDUCK_SHARE_URL,
    get_motherduck_token,
)

logger = logging.getLogger(__name__)

_connection: Optional[duckdb.DuckDBPyConnection] = None
_vss_available: bool = False
_is_share: bool = False


def get_connection() -> duckdb.DuckDBPyConnection:
    """Get or create MotherDuck DuckDB connection (singleton).

    Tries to connect as the database owner first. If that fails (e.g. the
    user doesn't own the database), falls back to attaching the public share
    in read-only mode.
    """
    global _connection, _is_share
    if _connection is None:
        token = get_motherduck_token()
        if not token:
            raise ValueError(
                "MOTHERDUCK_TOKEN environment variable is not set. "
                "Get a token from https://app.motherduck.com/settings"
            )
        try:
            _connection = duckdb.connect(f"md:{MOTHERDUCK_DATABASE}?motherduck_token={token}")
            _is_share = False
            _init_schema(_connection)
        except Exception as e:
            logger.info(f"Could not open database directly ({e}), attaching public share")
            _connection = duckdb.connect(f"md:?motherduck_token={token}")
            _connection.execute(f"ATTACH 'md:{MOTHERDUCK_SHARE_URL}'")
            _connection.execute(f"USE {MOTHERDUCK_DATABASE}")
            _is_share = True
    return _connection


def close_connection():
    """Close the database connection."""
    global _connection
    if _connection is not None:
        _connection.close()
        _connection = None


def is_vss_available() -> bool:
    """Check whether the VSS extension is available."""
    return _vss_available


def _init_schema(conn: duckdb.DuckDBPyConnection):
    """Initialize all knowledge graph tables if they don't exist."""
    global _vss_available

    # Try VSS extension for HNSW indexes
    try:
        conn.execute("INSTALL vss")
        conn.execute("LOAD vss")
        conn.execute("SET hnsw_enable_experimental_persistence = true")
        _vss_available = True
        logger.info("VSS extension loaded successfully")
    except Exception as e:
        _vss_available = False
        logger.warning(
            f"VSS extension unavailable ({e}). "
            "Vector search will use brute-force cosine similarity."
        )

    dims = EMBEDDING_DIMENSIONS

    # --- pipeline_metadata: idempotency tracking ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pipeline_metadata (
            key VARCHAR PRIMARY KEY,
            value VARCHAR NOT NULL
        )
    """)

    # --- concepts: graph nodes ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS concepts (
            id VARCHAR PRIMARY KEY,
            name VARCHAR UNIQUE NOT NULL,
            definition TEXT,
            category VARCHAR,
            page_references INTEGER[]
        )
    """)

    # --- sections: book sections ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sections (
            id VARCHAR PRIMARY KEY,
            title VARCHAR NOT NULL,
            chapter_number INTEGER,
            part_number INTEGER,
            line_start INTEGER,
            line_end INTEGER,
            approx_page_start INTEGER,
            approx_page_end INTEGER,
            summary TEXT,
            content TEXT
        )
    """)

    # Migrate: add content column if missing (existing tables)
    try:
        conn.execute("ALTER TABLE sections ADD COLUMN content TEXT")
        logger.info("Added content column to sections table")
    except Exception:
        pass  # Column already exists

    # --- concept_sections: concept <-> section mapping ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS concept_sections (
            concept_id VARCHAR NOT NULL,
            section_id VARCHAR NOT NULL,
            confidence FLOAT,
            is_primary BOOLEAN DEFAULT FALSE,
            PRIMARY KEY (concept_id, section_id)
        )
    """)

    # --- relationships: graph edges ---
    conn.execute("CREATE SEQUENCE IF NOT EXISTS relationships_id_seq")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS relationships (
            id INTEGER PRIMARY KEY DEFAULT nextval('relationships_id_seq'),
            from_concept_id VARCHAR NOT NULL,
            to_concept_id VARCHAR NOT NULL,
            relationship_type VARCHAR NOT NULL,
            confidence FLOAT,
            source_type VARCHAR,
            provenance_sections VARCHAR[],
            provenance_pages INTEGER[],
            description TEXT
        )
    """)

    # Sync sequence with existing data
    try:
        max_id = conn.execute("SELECT COALESCE(MAX(id), 0) FROM relationships").fetchone()[0]
        if max_id > 0:
            conn.execute(f"ALTER SEQUENCE relationships_id_seq RESTART WITH {max_id + 1}")
    except Exception as e:
        logger.warning(f"Could not sync relationships_id_seq: {e}")

    # --- concept_embeddings ---
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS concept_embeddings (
            concept_id VARCHAR PRIMARY KEY,
            embedding FLOAT[{dims}],
            embedded_text TEXT
        )
    """)

    # --- section_embeddings ---
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS section_embeddings (
            section_id VARCHAR PRIMARY KEY,
            embedding FLOAT[{dims}],
            embedded_text TEXT
        )
    """)

    # Create HNSW indexes if VSS available
    if _vss_available:
        for table, col in [
            ("concept_embeddings", "embedding"),
            ("section_embeddings", "embedding"),
        ]:
            try:
                conn.execute(f"""
                    CREATE INDEX IF NOT EXISTS {table}_hnsw_idx
                    ON {table} USING HNSW ({col})
                    WITH (metric = 'cosine')
                """)
            except Exception as e:
                logger.debug(f"Could not create HNSW index on {table}: {e}")

    logger.info("Schema initialized successfully")


# --- Query helpers ---

def get_stats() -> dict:
    """Get knowledge graph statistics."""
    conn = get_connection()

    concept_count = conn.execute("SELECT COUNT(*) FROM concepts").fetchone()[0]
    section_count = conn.execute("SELECT COUNT(*) FROM sections").fetchone()[0]
    relationship_count = conn.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
    concept_section_count = conn.execute("SELECT COUNT(*) FROM concept_sections").fetchone()[0]

    avg_confidence = conn.execute(
        "SELECT ROUND(AVG(confidence), 3) FROM relationships"
    ).fetchone()[0]

    # Relationship type breakdown
    rel_types = conn.execute(
        "SELECT relationship_type, COUNT(*) FROM relationships GROUP BY relationship_type ORDER BY COUNT(*) DESC"
    ).fetchall()

    # Category breakdown
    categories = conn.execute(
        "SELECT category, COUNT(*) FROM concepts WHERE category IS NOT NULL GROUP BY category ORDER BY COUNT(*) DESC"
    ).fetchall()

    # Pipeline metadata
    metadata = dict(
        conn.execute("SELECT key, value FROM pipeline_metadata").fetchall()
    )

    return {
        "concepts": concept_count,
        "sections": section_count,
        "relationships": relationship_count,
        "concept_section_mappings": concept_section_count,
        "avg_relationship_confidence": avg_confidence,
        "relationship_types": {r[0]: r[1] for r in rel_types},
        "concept_categories": {c[0]: c[1] for c in categories},
        "pipeline": metadata,
    }


def search_concepts_by_embedding(
    query_embedding: list[float],
    max_results: int = 10,
) -> list[dict]:
    """Search concepts by cosine similarity to a query embedding."""
    conn = get_connection()
    dims = EMBEDDING_DIMENSIONS

    results = conn.execute(f"""
        SELECT
            c.id, c.name, c.definition, c.category,
            array_cosine_similarity(ce.embedding, ?::FLOAT[{dims}]) as score
        FROM concept_embeddings ce
        JOIN concepts c ON ce.concept_id = c.id
        ORDER BY score DESC
        LIMIT ?
    """, [query_embedding, max_results]).fetchall()

    return [
        {
            "id": r[0],
            "name": r[1],
            "definition": r[2],
            "category": r[3],
            "score": round(r[4], 4) if r[4] else 0.0,
        }
        for r in results
    ]


def get_concept_relationships(
    concept_id: str,
    confidence_threshold: float = 0.0,
) -> list[dict]:
    """Get all relationships for a concept (both directions)."""
    conn = get_connection()

    results = conn.execute("""
        SELECT
            r.id, r.from_concept_id, r.to_concept_id,
            r.relationship_type, r.confidence,
            r.source_type, r.description,
            r.provenance_sections, r.provenance_pages,
            cf.name as from_name, ct.name as to_name
        FROM relationships r
        JOIN concepts cf ON r.from_concept_id = cf.id
        JOIN concepts ct ON r.to_concept_id = ct.id
        WHERE (r.from_concept_id = ? OR r.to_concept_id = ?)
          AND r.confidence >= ?
        ORDER BY r.confidence DESC
    """, [concept_id, concept_id, confidence_threshold]).fetchall()

    return [
        {
            "id": r[0],
            "from_concept_id": r[1],
            "to_concept_id": r[2],
            "relationship_type": r[3],
            "confidence": round(r[4], 3) if r[4] else None,
            "source_type": r[5],
            "description": r[6],
            "provenance_sections": r[7],
            "provenance_pages": r[8],
            "from_name": r[9],
            "to_name": r[10],
        }
        for r in results
    ]


def get_concept_sections(concept_id: str) -> list[dict]:
    """Get sections where a concept is discussed."""
    conn = get_connection()

    results = conn.execute("""
        SELECT
            s.id, s.title, s.chapter_number, s.part_number,
            s.approx_page_start, s.approx_page_end,
            cs.confidence, cs.is_primary, s.summary
        FROM concept_sections cs
        JOIN sections s ON cs.section_id = s.id
        WHERE cs.concept_id = ?
        ORDER BY cs.is_primary DESC, cs.confidence DESC
    """, [concept_id]).fetchall()

    return [
        {
            "section_id": r[0],
            "title": r[1],
            "chapter_number": r[2],
            "part_number": r[3],
            "approx_page_start": r[4],
            "approx_page_end": r[5],
            "confidence": round(r[6], 3) if r[6] else None,
            "is_primary": r[7],
            "summary": r[8],
        }
        for r in results
    ]


def find_concept_by_name(name: str) -> dict | None:
    """Find a concept by exact or fuzzy name match."""
    conn = get_connection()

    # Try exact match first
    result = conn.execute(
        "SELECT id, name, definition, category, page_references FROM concepts WHERE LOWER(name) = LOWER(?)",
        [name],
    ).fetchone()

    if not result:
        # Try contains match
        result = conn.execute(
            "SELECT id, name, definition, category, page_references FROM concepts WHERE LOWER(name) LIKE LOWER(?)",
            [f"%{name}%"],
        ).fetchone()

    if not result:
        return None

    return {
        "id": result[0],
        "name": result[1],
        "definition": result[2],
        "category": result[3],
        "page_references": result[4],
    }


def get_all_concepts() -> list[dict]:
    """Return all concepts ordered by category, name."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT id, name, definition, category
        FROM concepts
        ORDER BY category, name
    """).fetchall()
    return [
        {"id": r[0], "name": r[1], "definition": r[2], "category": r[3]}
        for r in rows
    ]


def get_subgraph(
    seed_concept_ids: list[str],
    max_hops: int = 2,
    confidence_threshold: float = 0.0,
) -> dict:
    """Multi-source BFS from seed concepts. Returns nodes and edges."""
    from collections import deque

    # Track nodes: concept_id -> {depth, is_seed, ...}
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    seen_edges: set[int] = set()

    conn = get_connection()

    # Initialize seeds
    for cid in seed_concept_ids:
        row = conn.execute(
            "SELECT id, name, definition, category FROM concepts WHERE id = ?",
            [cid],
        ).fetchone()
        if row:
            nodes[row[0]] = {
                "id": row[0],
                "name": row[1],
                "definition": row[2],
                "category": row[3],
                "depth": 0,
                "is_seed": True,
            }

    queue = deque((cid, 0) for cid in nodes)

    while queue:
        current_id, depth = queue.popleft()
        if depth >= max_hops:
            continue

        rels = get_concept_relationships(current_id, confidence_threshold)
        for rel in rels:
            # Record edge (deduplicate by relationship id)
            if rel["id"] not in seen_edges:
                seen_edges.add(rel["id"])
                edges.append({
                    "from_concept_id": rel["from_concept_id"],
                    "from_name": rel["from_name"],
                    "to_concept_id": rel["to_concept_id"],
                    "to_name": rel["to_name"],
                    "relationship_type": rel["relationship_type"],
                    "confidence": rel["confidence"],
                    "source_type": rel["source_type"],
                    "description": rel["description"],
                })

            # Discover neighbour
            next_id = (
                rel["to_concept_id"]
                if rel["from_concept_id"] == current_id
                else rel["from_concept_id"]
            )
            if next_id not in nodes:
                row = conn.execute(
                    "SELECT id, name, definition, category FROM concepts WHERE id = ?",
                    [next_id],
                ).fetchone()
                if row:
                    nodes[next_id] = {
                        "id": row[0],
                        "name": row[1],
                        "definition": row[2],
                        "category": row[3],
                        "depth": depth + 1,
                        "is_seed": False,
                    }
                    queue.append((next_id, depth + 1))

    return {
        "nodes": list(nodes.values()),
        "edges": edges,
    }


def search_sections_by_embedding(
    query_embedding: list[float],
    max_results: int = 5,
    concept_ids: list[str] | None = None,
) -> list[dict]:
    """Cosine similarity search over section embeddings.

    Optionally scoped to sections linked to given concept_ids.
    """
    conn = get_connection()
    dims = EMBEDDING_DIMENSIONS

    if concept_ids:
        placeholders = ", ".join("?" for _ in concept_ids)
        results = conn.execute(f"""
            SELECT DISTINCT
                s.id, s.title, s.chapter_number, s.part_number,
                s.approx_page_start, s.approx_page_end, s.content,
                array_cosine_similarity(se.embedding, ?::FLOAT[{dims}]) as score
            FROM section_embeddings se
            JOIN sections s ON se.section_id = s.id
            JOIN concept_sections cs ON cs.section_id = s.id
            WHERE cs.concept_id IN ({placeholders})
            ORDER BY score DESC
            LIMIT ?
        """, [query_embedding, *concept_ids, max_results]).fetchall()
    else:
        results = conn.execute(f"""
            SELECT
                s.id, s.title, s.chapter_number, s.part_number,
                s.approx_page_start, s.approx_page_end, s.content,
                array_cosine_similarity(se.embedding, ?::FLOAT[{dims}]) as score
            FROM section_embeddings se
            JOIN sections s ON se.section_id = s.id
            ORDER BY score DESC
            LIMIT ?
        """, [query_embedding, max_results]).fetchall()

    return [
        {
            "section_id": r[0],
            "title": r[1],
            "chapter_number": r[2],
            "part_number": r[3],
            "approx_page_start": r[4],
            "approx_page_end": r[5],
            "content": r[6],
            "score": round(r[7], 4) if r[7] else 0.0,
        }
        for r in results
    ]
