"""
Local DuckDB database module for the knowledge graph.

Handles connection management (singleton) and schema initialization for all
knowledge graph tables.

The database is a local file (path resolved by config.get_db_path). MotherDuck
is no longer a deployment target — see docs/multi-book-architecture-plan.md.
"""

import logging
from typing import Optional

import duckdb

from iconsult_mcp.config import EMBEDDING_DIMENSIONS, get_db_path

logger = logging.getLogger(__name__)

_connection: Optional[duckdb.DuckDBPyConnection] = None
_vss_available: bool = False
_step_buffer: dict[str, list[dict]] = {}


def get_connection() -> duckdb.DuckDBPyConnection:
    """Get or create the local DuckDB connection (singleton)."""
    global _connection
    if _connection is None:
        path = get_db_path()
        _connection = duckdb.connect(path)
        logger.info(f"Opened local DuckDB at {path}")
        _init_schema(_connection)
    return _connection


def close_connection():
    """Close the database connection."""
    global _connection
    if _connection is not None:
        flush_all_steps()
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

    # --- books: corpus catalogue (multi-book refactor, Phase 1a) ---
    # One row per ingested book. The summary_embedding powers triage in Phase 2;
    # is_oracle marks the book whose Ch. 12 supplies the scoring rubric.
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS books (
            id VARCHAR PRIMARY KEY,
            title VARCHAR NOT NULL,
            authors VARCHAR,
            year INTEGER,
            summary TEXT,
            summary_embedding FLOAT[{dims}],
            altitude VARCHAR,
            is_oracle BOOLEAN DEFAULT FALSE,
            chapter_boundaries JSON,
            created_at TIMESTAMP DEFAULT current_timestamp
        )
    """)

    # --- concepts: graph nodes ---
    # Multi-book design: `(name, book_id)` UNIQUE, not `name` alone — the
    # same concept name can legitimately appear in multiple books, and
    # Phase 3 alignment is what reconciles them across books. Existing
    # databases created before this design migrate via
    # `_migrate_concepts_name_unique` below.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS concepts (
            id VARCHAR PRIMARY KEY,
            name VARCHAR NOT NULL,
            definition TEXT,
            category VARCHAR,
            page_references INTEGER[],
            book_id VARCHAR,
            UNIQUE (name, book_id)
        )
    """)

    # Migrate: add book_id column if missing (multi-book refactor, Phase 1a).
    # Initially nullable; populated by the rebuilt pipeline in Stage 1c. Skipped
    # silently when the column already exists (fresh DBs hit the new CREATE).
    try:
        conn.execute("ALTER TABLE concepts ADD COLUMN book_id VARCHAR")
        logger.info("Added book_id column to concepts table")
    except Exception:
        pass  # Column already exists

    # Migrate: drop legacy column-level UNIQUE on `name`, install composite
    # UNIQUE on (name, book_id). Idempotent — see helper docstring.
    _migrate_concepts_name_unique(conn)

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

    # Migrate: add book_id column if missing (multi-book refactor, Phase 1a)
    try:
        conn.execute("ALTER TABLE sections ADD COLUMN book_id VARCHAR")
        logger.info("Added book_id column to sections table")
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

    # Migrate: add book_id column if missing (multi-book refactor, Phase 1a)
    try:
        conn.execute("ALTER TABLE relationships ADD COLUMN book_id VARCHAR")
        logger.info("Added book_id column to relationships table")
    except Exception:
        pass  # Column already exists

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

    # --- consultations: reproducible consultation sessions ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS consultations (
            id VARCHAR PRIMARY KEY,
            project_fingerprint VARCHAR NOT NULL,
            project_description TEXT NOT NULL,
            matched_concept_ids VARCHAR[] NOT NULL,
            matched_scores FLOAT[],
            steps JSON DEFAULT '[]',
            created_at TIMESTAMP DEFAULT current_timestamp
        )
    """)

    # --- consultation_state: shared epistemic memory (upsert-by-key) ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS consultation_state (
            consultation_id VARCHAR NOT NULL,
            key VARCHAR NOT NULL,
            value_json JSON,
            updated_at TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (consultation_id, key)
        )
    """)

    # --- consultation_events: event-driven reactivity (poll-based) ---
    conn.execute("CREATE SEQUENCE IF NOT EXISTS consultation_events_id_seq")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS consultation_events (
            id INTEGER PRIMARY KEY DEFAULT nextval('consultation_events_id_seq'),
            consultation_id VARCHAR NOT NULL,
            event_type VARCHAR NOT NULL,
            data JSON DEFAULT '{}',
            created_at TIMESTAMP DEFAULT current_timestamp
        )
    """)

    # Sync events sequence with existing data
    try:
        max_eid = conn.execute(
            "SELECT COALESCE(MAX(id), 0) FROM consultation_events"
        ).fetchone()[0]
        if max_eid > 0:
            conn.execute(
                f"ALTER SEQUENCE consultation_events_id_seq RESTART WITH {max_eid + 1}"
            )
    except Exception as e:
        logger.warning(f"Could not sync consultation_events_id_seq: {e}")

    # --- implementation_plans: persistent implementation plan storage ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS implementation_plans (
            consultation_id VARCHAR PRIMARY KEY,
            plan_json JSON NOT NULL,
            markdown_path VARCHAR,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # --- consultation_quality: quality ratings and feedback ---
    conn.execute("CREATE SEQUENCE IF NOT EXISTS consultation_quality_id_seq")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS consultation_quality (
            id INTEGER PRIMARY KEY DEFAULT nextval('consultation_quality_id_seq'),
            consultation_id VARCHAR NOT NULL,
            rating INTEGER,
            feedback TEXT,
            concept_coverage FLOAT,
            pattern_count INTEGER,
            maturity_level INTEGER,
            created_at TIMESTAMP DEFAULT current_timestamp
        )
    """)

    # --- blackboard_facts: typed, versioned facts for scatter-gather coordination ---
    conn.execute("CREATE SEQUENCE IF NOT EXISTS blackboard_facts_id_seq")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS blackboard_facts (
            id INTEGER PRIMARY KEY DEFAULT nextval('blackboard_facts_id_seq'),
            consultation_id VARCHAR NOT NULL,
            fact_type VARCHAR NOT NULL,
            key VARCHAR NOT NULL,
            value_json JSON,
            confidence FLOAT DEFAULT 1.0,
            agent_id VARCHAR,
            version INTEGER DEFAULT 1,
            expires_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT current_timestamp
        )
    """)

    # --- Phase 3a: per-project canonical layer ---------------------------------
    # `projects` caches the triage outcome for a (name, description) pair. The
    # unified KG (canonical_concepts) is built once per project and reused across
    # follow-up consultations on the same project.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id VARCHAR PRIMARY KEY,
            name VARCHAR NOT NULL,
            description TEXT NOT NULL,
            triaged_book_ids VARCHAR[],
            unified_kg_built_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT current_timestamp
        )
    """)

    # `canonical_concepts` is the project-scoped alignment layer. Each row is a
    # cluster of source concepts (from one or more triaged books) that the
    # alignment step adjudicated as the same concept. `role` distinguishes
    # supporting-evidence concepts (anchored to a Ch. 12 rubric pattern) from
    # informational-only ones (enrich the consultation but never score).
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS canonical_concepts (
            id VARCHAR PRIMARY KEY,
            project_id VARCHAR NOT NULL,
            name VARCHAR NOT NULL,
            member_concept_ids VARCHAR[] NOT NULL,
            role VARCHAR NOT NULL CHECK (role IN ('supporting_evidence', 'informational_only')),
            rubric_pattern_id VARCHAR,
            canonical_embedding FLOAT[{dims}]
        )
    """)

    # `concept_alignment_cache` is global (NOT project-scoped). Two projects
    # whose triaged book sets overlap reuse alignment verdicts from this cache,
    # so the LLM cost of pairwise adjudication amortizes across the user base.
    # Writer enforces canonical pair-order (concept_a.book_id < concept_b.book_id)
    # so each pair has exactly one cache row.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS concept_alignment_cache (
            concept_a_id VARCHAR NOT NULL,
            concept_b_id VARCHAR NOT NULL,
            same_concept BOOLEAN NOT NULL,
            confidence FLOAT,
            rationale TEXT,
            created_at TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (concept_a_id, concept_b_id)
        )
    """)

    logger.info("Schema initialized successfully")


def _migrate_concepts_name_unique(conn: duckdb.DuckDBPyConnection) -> bool:
    """Migrate concepts.name UNIQUE → UNIQUE(name, book_id). Idempotent.

    The single-book schema enforced `name VARCHAR UNIQUE NOT NULL`. With
    multi-book ingestion the same concept name legitimately appears in more
    than one book (e.g., "MCP" in both Arsanjani 2026 and Gulli 2025), and
    that's *exactly* what Phase 3 alignment reconciles. The old constraint
    silently rejected the second-book copy, dropping the highest-confidence
    cross-book alignment candidates.

    Performs a table swap: create `concepts_new` with the new constraint,
    copy all rows (`id` PKs preserved so soft references in
    relationships / concept_sections / concept_embeddings keep working),
    drop the old, rename. Wrapped in a transaction.

    Returns True if the migration ran, False if the schema is already
    correct (fresh DBs, or DBs already migrated).
    """
    rows = conn.execute(
        """
        SELECT constraint_type, constraint_column_names
        FROM duckdb_constraints()
        WHERE table_name = 'concepts'
        """
    ).fetchall()

    has_old = False
    has_new = False
    for ctype, cols in rows:
        if ctype != "UNIQUE":
            continue
        col_set = sorted(cols)
        if col_set == ["name"]:
            has_old = True
        elif col_set == ["book_id", "name"]:
            has_new = True

    if has_new and not has_old:
        return False  # already migrated (or fresh DB hit the new CREATE)
    if not has_old:
        return False  # neither — nothing to do

    logger.info("Migrating concepts.name UNIQUE → UNIQUE(name, book_id)")

    conn.execute("BEGIN")
    try:
        conn.execute(
            """
            CREATE TABLE concepts_new (
                id VARCHAR PRIMARY KEY,
                name VARCHAR NOT NULL,
                definition TEXT,
                category VARCHAR,
                page_references INTEGER[],
                book_id VARCHAR,
                UNIQUE (name, book_id)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO concepts_new
                (id, name, definition, category, page_references, book_id)
            SELECT id, name, definition, category, page_references, book_id
            FROM concepts
            """
        )
        conn.execute("DROP TABLE concepts")
        conn.execute("ALTER TABLE concepts_new RENAME TO concepts")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    logger.info("Migration complete: UNIQUE(name, book_id) installed on concepts")
    return True


# --- Books registry helpers --------------------------------------------------


def upsert_book(
    book_id: str,
    title: str,
    authors: str | None = None,
    year: int | None = None,
    altitude: str | None = None,
    is_oracle: bool = False,
    chapter_boundaries: dict | list | None = None,
) -> None:
    """Insert or replace a row in the `books` corpus catalogue.

    Writes only metadata + chapter_boundaries. `summary` and
    `summary_embedding` are not in the column list, so they are preserved
    on re-seed (DuckDB's INSERT OR REPLACE keeps columns absent from the
    INSERT). The canonical writer for those is `set_book_summary` — keep
    metadata seeding and summary committing on separate paths so a re-seed
    of metadata never nukes the embedding, and a re-commit of the summary
    never nukes the metadata.

    `chapter_boundaries` is JSON-serialized.
    """
    import json as _json

    conn = get_connection()
    boundaries_json = (
        _json.dumps(chapter_boundaries) if chapter_boundaries is not None else None
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO books
            (id, title, authors, year, altitude, is_oracle, chapter_boundaries)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [book_id, title, authors, year, altitude, is_oracle, boundaries_json],
    )


def set_book_summary(
    book_id: str,
    summary: str,
    summary_embedding: list[float],
) -> None:
    """Update `summary` and `summary_embedding` for an existing book row.

    Raises KeyError if the book row does not exist (run `seed_books_table.py`
    first). Phase 2a writer; intentionally separate from `upsert_book` so a
    re-seed of metadata never nukes the embedding, and a re-commit of the
    summary never nukes the metadata.
    """
    conn = get_connection()
    existing = conn.execute(
        "SELECT 1 FROM books WHERE id = ?", [book_id]
    ).fetchone()
    if not existing:
        raise KeyError(
            f"Book '{book_id}' not found in books table. "
            "Run `py scripts/seed_books_table.py` first."
        )
    conn.execute(
        """
        UPDATE books
           SET summary = ?,
               summary_embedding = ?
         WHERE id = ?
        """,
        [summary, summary_embedding, book_id],
    )


def get_book(book_id: str) -> dict | None:
    """Return the row for one book or None."""
    import json as _json

    conn = get_connection()
    row = conn.execute(
        """
        SELECT id, title, authors, year, summary, altitude, is_oracle,
               chapter_boundaries, created_at,
               summary_embedding IS NOT NULL AS has_summary_embedding
        FROM books
        WHERE id = ?
        """,
        [book_id],
    ).fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "title": row[1],
        "authors": row[2],
        "year": row[3],
        "summary": row[4],
        "altitude": row[5],
        "is_oracle": row[6],
        "chapter_boundaries": _json.loads(row[7]) if row[7] else None,
        "created_at": row[8],
        "has_summary_embedding": bool(row[9]),
    }


def list_books(altitude: str | None = None) -> list[dict]:
    """Return all rows in the `books` table, optionally filtered by altitude."""
    import json as _json

    conn = get_connection()
    if altitude is not None:
        rows = conn.execute(
            """
            SELECT id, title, authors, year, altitude, is_oracle, chapter_boundaries
            FROM books
            WHERE altitude = ?
            ORDER BY created_at
            """,
            [altitude],
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, title, authors, year, altitude, is_oracle, chapter_boundaries
            FROM books
            ORDER BY created_at
            """
        ).fetchall()
    return [
        {
            "id": r[0],
            "title": r[1],
            "authors": r[2],
            "year": r[3],
            "altitude": r[4],
            "is_oracle": r[5],
            "chapter_boundaries": _json.loads(r[6]) if r[6] else None,
        }
        for r in rows
    ]


# --- Project / canonical layer helpers (Phase 3a) ----------------------------


def create_project(
    project_id: str,
    name: str,
    description: str,
    triaged_book_ids: list[str] | None = None,
) -> None:
    """Insert or replace a row in the `projects` cache.

    `unified_kg_built_at` is left NULL — `build_project_kg` (Phase 3c) sets it
    after a successful alignment pass.
    """
    conn = get_connection()
    conn.execute(
        """
        INSERT OR REPLACE INTO projects
            (id, name, description, triaged_book_ids, unified_kg_built_at)
        VALUES (?, ?, ?, ?, NULL)
        """,
        [project_id, name, description, triaged_book_ids or []],
    )


def get_project(project_id: str) -> dict | None:
    """Return one project row or None."""
    conn = get_connection()
    row = conn.execute(
        """
        SELECT id, name, description, triaged_book_ids,
               unified_kg_built_at, created_at
        FROM projects
        WHERE id = ?
        """,
        [project_id],
    ).fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "name": row[1],
        "description": row[2],
        "triaged_book_ids": list(row[3]) if row[3] is not None else [],
        "unified_kg_built_at": str(row[4]) if row[4] else None,
        "created_at": str(row[5]) if row[5] else None,
    }


def list_projects() -> list[dict]:
    """Return all project rows ordered by creation time."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT id, name, description, triaged_book_ids,
               unified_kg_built_at, created_at
        FROM projects
        ORDER BY created_at
        """
    ).fetchall()
    return [
        {
            "id": r[0],
            "name": r[1],
            "description": r[2],
            "triaged_book_ids": list(r[3]) if r[3] is not None else [],
            "unified_kg_built_at": str(r[4]) if r[4] else None,
            "created_at": str(r[5]) if r[5] else None,
        }
        for r in rows
    ]


def mark_project_kg_built(project_id: str) -> None:
    """Set `unified_kg_built_at = now` for a project. Called by `build_project_kg`."""
    conn = get_connection()
    conn.execute(
        "UPDATE projects SET unified_kg_built_at = current_timestamp WHERE id = ?",
        [project_id],
    )


def upsert_canonical_concept(
    canonical_id: str,
    project_id: str,
    name: str,
    member_concept_ids: list[str],
    role: str,
    rubric_pattern_id: str | None = None,
    canonical_embedding: list[float] | None = None,
) -> None:
    """Insert or replace a canonical concept row.

    Args:
        canonical_id: `{project_id}__{slug}` PK.
        project_id: Owning project.
        name: Canonical name (usually from oracle book if a member maps there).
        member_concept_ids: Source concepts (from various books) that resolve
            here. Must contain at least one ID.
        role: 'supporting_evidence' or 'informational_only'.
        rubric_pattern_id: Canonical Ch. 12 pattern ID, or None if informational.
        canonical_embedding: Mean of member embeddings (computed by caller).
    """
    if role not in ("supporting_evidence", "informational_only"):
        raise ValueError(
            f"role must be 'supporting_evidence' or 'informational_only', got {role!r}"
        )
    if not member_concept_ids:
        raise ValueError("member_concept_ids must contain at least one concept ID")

    conn = get_connection()
    conn.execute(
        """
        INSERT OR REPLACE INTO canonical_concepts
            (id, project_id, name, member_concept_ids, role,
             rubric_pattern_id, canonical_embedding)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            canonical_id,
            project_id,
            name,
            member_concept_ids,
            role,
            rubric_pattern_id,
            canonical_embedding,
        ],
    )


def get_canonical_concept(canonical_id: str) -> dict | None:
    """Return one canonical concept row or None."""
    conn = get_connection()
    row = conn.execute(
        """
        SELECT id, project_id, name, member_concept_ids, role,
               rubric_pattern_id,
               canonical_embedding IS NOT NULL AS has_embedding
        FROM canonical_concepts
        WHERE id = ?
        """,
        [canonical_id],
    ).fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "project_id": row[1],
        "name": row[2],
        "member_concept_ids": list(row[3]) if row[3] is not None else [],
        "role": row[4],
        "rubric_pattern_id": row[5],
        "has_embedding": bool(row[6]),
    }


def list_canonical_concepts(project_id: str) -> list[dict]:
    """Return all canonical concepts for a project."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT id, project_id, name, member_concept_ids, role,
               rubric_pattern_id,
               canonical_embedding IS NOT NULL AS has_embedding
        FROM canonical_concepts
        WHERE project_id = ?
        ORDER BY name
        """,
        [project_id],
    ).fetchall()
    return [
        {
            "id": r[0],
            "project_id": r[1],
            "name": r[2],
            "member_concept_ids": list(r[3]) if r[3] is not None else [],
            "role": r[4],
            "rubric_pattern_id": r[5],
            "has_embedding": bool(r[6]),
        }
        for r in rows
    ]


def _canonical_pair(concept_a_id: str, concept_b_id: str) -> tuple[str, str]:
    """Return the (a, b) tuple in canonical lexicographic order.

    The cache key is a single ordered pair regardless of caller direction.
    The plan calls for `a.book_id < b.book_id`, but since concept IDs are
    `{book_id}__{slug}` namespaced, lexicographic order on the IDs themselves
    yields the same ordering for distinct books.
    """
    if concept_a_id == concept_b_id:
        raise ValueError("Cannot align a concept with itself")
    return (
        (concept_a_id, concept_b_id)
        if concept_a_id < concept_b_id
        else (concept_b_id, concept_a_id)
    )


def record_alignment_decision(
    concept_a_id: str,
    concept_b_id: str,
    same_concept: bool,
    confidence: float | None = None,
    rationale: str | None = None,
) -> None:
    """Record an alignment verdict for a concept pair (idempotent).

    Pair is normalized to canonical order before insert, so callers may pass
    either direction. Re-inserting overwrites the prior verdict.
    """
    a, b = _canonical_pair(concept_a_id, concept_b_id)
    conn = get_connection()
    conn.execute(
        """
        INSERT OR REPLACE INTO concept_alignment_cache
            (concept_a_id, concept_b_id, same_concept, confidence, rationale, created_at)
        VALUES (?, ?, ?, ?, ?, current_timestamp)
        """,
        [a, b, bool(same_concept), confidence, rationale],
    )


def get_alignment_decision(
    concept_a_id: str,
    concept_b_id: str,
) -> dict | None:
    """Return a cached alignment verdict for a concept pair, or None.

    Pair is normalized to canonical order before lookup.
    """
    a, b = _canonical_pair(concept_a_id, concept_b_id)
    conn = get_connection()
    row = conn.execute(
        """
        SELECT concept_a_id, concept_b_id, same_concept, confidence,
               rationale, created_at
        FROM concept_alignment_cache
        WHERE concept_a_id = ? AND concept_b_id = ?
        """,
        [a, b],
    ).fetchone()
    if not row:
        return None
    return {
        "concept_a_id": row[0],
        "concept_b_id": row[1],
        "same_concept": bool(row[2]),
        "confidence": row[3],
        "rationale": row[4],
        "created_at": str(row[5]) if row[5] else None,
    }


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


def search_books_by_embedding(
    query_embedding: list[float],
    max_results: int = 5,
    threshold: float = 0.0,
) -> list[dict]:
    """Cosine similarity over books.summary_embedding (Phase 2b triage).

    Skips books whose summary_embedding is NULL. Deterministic for a given
    embedding input. Returns `score` rounded to 4 decimals to match the
    existing concept-search style.
    """
    conn = get_connection()
    dims = EMBEDDING_DIMENSIONS

    rows = conn.execute(f"""
        SELECT
            id, title, altitude, is_oracle,
            array_cosine_similarity(summary_embedding, ?::FLOAT[{dims}]) AS score
        FROM books
        WHERE summary_embedding IS NOT NULL
        ORDER BY score DESC
        LIMIT ?
    """, [query_embedding, max_results]).fetchall()

    out = []
    for r in rows:
        score = round(r[4], 4) if r[4] is not None else 0.0
        if score < threshold:
            continue
        out.append({
            "id": r[0],
            "title": r[1],
            "altitude": r[2],
            "is_oracle": bool(r[3]),
            "score": score,
        })
    return out


def search_concepts_by_embedding(
    query_embedding: list[float],
    max_results: int = 10,
    book_id: str | None = None,
) -> list[dict]:
    """Search concepts by cosine similarity to a query embedding.

    Args:
        query_embedding: The query vector (1536-d).
        max_results: Maximum results to return.
        book_id: Optional. When provided, restrict results to concepts from
            this book (multi-book refactor). When None, search all books.
    """
    conn = get_connection()
    dims = EMBEDDING_DIMENSIONS

    where_clause = ""
    params: list = [query_embedding]
    if book_id is not None:
        where_clause = "WHERE c.book_id = ?"
        params.append(book_id)
    params.append(max_results)

    results = conn.execute(f"""
        SELECT
            c.id, c.name, c.definition, c.category,
            array_cosine_similarity(ce.embedding, ?::FLOAT[{dims}]) as score
        FROM concept_embeddings ce
        JOIN concepts c ON ce.concept_id = c.id
        {where_clause}
        ORDER BY score DESC
        LIMIT ?
    """, params).fetchall()

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
    book_id: str | None = None,
) -> list[dict]:
    """Get all relationships for a concept (both directions).

    Args:
        concept_id: The concept whose edges to fetch.
        confidence_threshold: Minimum edge confidence to return.
        book_id: Optional. When provided, restrict to edges from this book
            (multi-book refactor). When None, return edges across all books.
    """
    conn = get_connection()

    book_clause = ""
    params: list = [concept_id, concept_id, confidence_threshold]
    if book_id is not None:
        book_clause = "AND r.book_id = ?"
        params.append(book_id)

    results = conn.execute(f"""
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
          {book_clause}
        ORDER BY r.confidence DESC
    """, params).fetchall()

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


def get_all_concepts(
    include_definitions: bool = False,
    search: str | None = None,
) -> list[dict]:
    """Return all concepts ordered by category, name.

    Args:
        include_definitions: Include definition text (default: False for compact output).
        search: Filter concepts whose name contains this substring (case-insensitive).
    """
    conn = get_connection()

    if include_definitions:
        select = "id, name, definition, category"
    else:
        select = "id, name, category"

    if search:
        rows = conn.execute(
            f"SELECT {select} FROM concepts WHERE LOWER(name) LIKE LOWER(?) ORDER BY category, name",
            [f"%{search}%"],
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT {select} FROM concepts ORDER BY category, name"
        ).fetchall()

    if include_definitions:
        return [
            {"id": r[0], "name": r[1], "definition": r[2], "category": r[3]}
            for r in rows
        ]
    return [
        {"id": r[0], "name": r[1], "category": r[2]}
        for r in rows
    ]


def search_concepts(query: str, include_definitions: bool = False) -> list[dict]:
    """Convenience wrapper: search concepts by name substring."""
    return get_all_concepts(include_definitions=include_definitions, search=query)


def get_subgraph(
    seed_concept_ids: list[str],
    max_hops: int = 2,
    confidence_threshold: float = 0.5,
    max_edges: int = 50,
    include_descriptions: bool = False,
) -> dict:
    """Priority-queue traversal from seed concepts. Returns compact nodes and edges.

    Explores highest-confidence edges first. Node discovery continues past the
    edge cap so the nodes list is comprehensive; only edges are truncated.

    Args:
        seed_concept_ids: Concept IDs to start from.
        max_hops: Maximum traversal depth (default 2).
        confidence_threshold: Minimum edge confidence (default 0.5).
        max_edges: Maximum edges to return (default 50). Edges beyond this
            are still traversed for node discovery but not included in output.
        include_descriptions: Include edge description text (default False).
    """
    import heapq

    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    seen_edges: set[int] = set()
    total_edges_found = 0

    conn = get_connection()

    # Initialize seeds
    for cid in seed_concept_ids:
        row = conn.execute(
            "SELECT id, name, category FROM concepts WHERE id = ?",
            [cid],
        ).fetchone()
        if row:
            nodes[row[0]] = {
                "id": row[0],
                "name": row[1],
                "category": row[2],
                "depth": 0,
                "is_seed": True,
            }

    # Priority queue: (-confidence, concept_id, depth) — negate for max-heap
    pq: list[tuple[float, str, int]] = []
    for cid in nodes:
        heapq.heappush(pq, (0.0, cid, 0))  # seeds at depth 0, priority 0

    explored: set[str] = set()

    while pq:
        _neg_conf, current_id, depth = heapq.heappop(pq)
        if current_id in explored:
            continue
        explored.add(current_id)

        if depth >= max_hops:
            continue

        rels = get_concept_relationships(current_id, confidence_threshold)
        for rel in rels:
            if rel["id"] in seen_edges:
                continue
            seen_edges.add(rel["id"])
            total_edges_found += 1

            # Build compact edge; only add to output if under cap
            if len(edges) < max_edges:
                edge = {
                    "from": rel["from_concept_id"],
                    "to": rel["to_concept_id"],
                    "type": rel["relationship_type"],
                    "confidence": rel["confidence"],
                }
                if include_descriptions and rel.get("description"):
                    edge["description"] = rel["description"]
                edges.append(edge)

            # Discover neighbour (always, even past edge cap)
            next_id = (
                rel["to_concept_id"]
                if rel["from_concept_id"] == current_id
                else rel["from_concept_id"]
            )
            if next_id not in nodes:
                row = conn.execute(
                    "SELECT id, name, category FROM concepts WHERE id = ?",
                    [next_id],
                ).fetchone()
                if row:
                    nodes[next_id] = {
                        "id": row[0],
                        "name": row[1],
                        "category": row[2],
                        "depth": depth + 1,
                        "is_seed": False,
                    }
            if next_id not in explored:
                edge_conf = rel["confidence"] if rel["confidence"] else 0.0
                heapq.heappush(pq, (-edge_conf, next_id, depth + 1))

    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "truncated": total_edges_found > max_edges,
        "total_edges_found": total_edges_found,
    }


def create_consultation(
    consultation_id: str,
    fingerprint: str,
    description: str,
    concept_ids: list[str],
    scores: list[float],
) -> None:
    """Create a new consultation record."""
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO consultations (id, project_fingerprint, project_description, matched_concept_ids, matched_scores) VALUES (?, ?, ?, ?, ?)",
        [consultation_id, fingerprint, description, concept_ids, scores],
    )


def log_consultation_step(
    consultation_id: str,
    step_type: str,
    data: dict,
) -> None:
    """Buffer a step for later batch flush (no DB write)."""
    step = {"type": step_type, **data}
    if consultation_id not in _step_buffer:
        _step_buffer[consultation_id] = []
    _step_buffer[consultation_id].append(step)


def flush_consultation_steps(consultation_id: str) -> int:
    """Batch-flush buffered steps for a consultation. Returns count flushed."""
    import json as _json

    pending = _step_buffer.pop(consultation_id, None)
    if not pending:
        return 0

    conn = get_connection()
    row = conn.execute(
        "SELECT steps FROM consultations WHERE id = ?",
        [consultation_id],
    ).fetchone()
    if not row:
        # Consultation was deleted; discard buffer
        return 0

    current_steps = _json.loads(row[0]) if row[0] else []
    current_steps.extend(pending)
    conn.execute(
        "UPDATE consultations SET steps = ? WHERE id = ?",
        [_json.dumps(current_steps), consultation_id],
    )
    return len(pending)


def flush_all_steps() -> int:
    """Flush buffered steps for all consultations. Returns total count flushed."""
    total = 0
    for cid in list(_step_buffer.keys()):
        total += flush_consultation_steps(cid)
    return total


def get_pending_steps(consultation_id: str) -> list[dict]:
    """Read-only view of buffered steps (for testing)."""
    return list(_step_buffer.get(consultation_id, []))


def discard_pending_steps(consultation_id: str) -> int:
    """Clear buffer without flushing (for test cleanup). Returns count discarded."""
    return len(_step_buffer.pop(consultation_id, []))


def get_consultation(consultation_id: str) -> dict | None:
    """Return a full consultation record. Auto-flushes buffered steps first."""
    import json as _json

    flush_consultation_steps(consultation_id)
    conn = get_connection()
    row = conn.execute(
        "SELECT id, project_fingerprint, project_description, matched_concept_ids, matched_scores, steps, created_at FROM consultations WHERE id = ?",
        [consultation_id],
    ).fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "project_fingerprint": row[1],
        "project_description": row[2],
        "matched_concept_ids": row[3],
        "matched_scores": row[4],
        "steps": _json.loads(row[5]) if row[5] else [],
        "created_at": str(row[6]),
    }


def get_consultations_by_fingerprint(fingerprint: str) -> list[dict]:
    """Find all consultation sessions for the same project fingerprint."""
    import json as _json

    flush_all_steps()
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, project_fingerprint, matched_concept_ids, matched_scores, steps, created_at FROM consultations WHERE project_fingerprint = ? ORDER BY created_at DESC",
        [fingerprint],
    ).fetchall()
    return [
        {
            "id": r[0],
            "project_fingerprint": r[1],
            "matched_concept_ids": r[2],
            "matched_scores": r[3],
            "steps": _json.loads(r[4]) if r[4] else [],
            "created_at": str(r[5]),
        }
        for r in rows
    ]


def get_pattern_assessments(consultation_id: str) -> list[dict]:
    """Extract pattern_assessment steps from a consultation's step log."""
    import json as _json

    flush_consultation_steps(consultation_id)
    conn = get_connection()
    row = conn.execute(
        "SELECT steps FROM consultations WHERE id = ?",
        [consultation_id],
    ).fetchone()
    if not row:
        return []

    steps = _json.loads(row[0]) if row[0] else []
    return [s for s in steps if s.get("type") == "pattern_assessment"]


# --- Shared state helpers ---


def write_shared_state(
    consultation_id: str,
    key: str,
    value: object,
) -> None:
    """Upsert a key-value pair in consultation shared state."""
    import json as _json

    conn = get_connection()
    conn.execute(
        """INSERT OR REPLACE INTO consultation_state
           (consultation_id, key, value_json, updated_at)
           VALUES (?, ?, ?, current_timestamp)""",
        [consultation_id, key, _json.dumps(value)],
    )


def read_shared_state(
    consultation_id: str,
    key: str | None = None,
) -> list[dict]:
    """Read shared state entries for a consultation.

    Args:
        consultation_id: The consultation session ID.
        key: Specific key to read, or None for all entries.

    Returns:
        List of dicts with key, value, updated_at.
    """
    import json as _json

    conn = get_connection()
    if key:
        rows = conn.execute(
            "SELECT key, value_json, updated_at FROM consultation_state WHERE consultation_id = ? AND key = ?",
            [consultation_id, key],
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT key, value_json, updated_at FROM consultation_state WHERE consultation_id = ? ORDER BY key",
            [consultation_id],
        ).fetchall()

    return [
        {
            "key": r[0],
            "value": _json.loads(r[1]) if r[1] else None,
            "updated_at": str(r[2]),
        }
        for r in rows
    ]


def delete_shared_state(
    consultation_id: str,
    key: str | None = None,
) -> int:
    """Delete shared state entries. Returns number of rows deleted."""
    conn = get_connection()
    if key:
        result = conn.execute(
            "DELETE FROM consultation_state WHERE consultation_id = ? AND key = ?",
            [consultation_id, key],
        )
    else:
        result = conn.execute(
            "DELETE FROM consultation_state WHERE consultation_id = ?",
            [consultation_id],
        )
    return result.fetchone()[0] if result.description else 0


# --- Consultation event helpers ---


def emit_consultation_event(
    consultation_id: str,
    event_type: str,
    data: dict,
) -> int:
    """Emit a consultation event. Returns the event ID."""
    import json as _json

    conn = get_connection()
    row = conn.execute(
        """INSERT INTO consultation_events (consultation_id, event_type, data)
           VALUES (?, ?, ?)
           RETURNING id""",
        [consultation_id, event_type, _json.dumps(data)],
    ).fetchone()
    return row[0]


def get_consultation_events(
    consultation_id: str,
    since_id: int | None = None,
    event_type: str | None = None,
) -> list[dict]:
    """Poll consultation events with optional filters."""
    import json as _json

    conn = get_connection()
    query = "SELECT id, event_type, data, created_at FROM consultation_events WHERE consultation_id = ?"
    params: list = [consultation_id]

    if since_id is not None:
        query += " AND id > ?"
        params.append(since_id)
    if event_type is not None:
        query += " AND event_type = ?"
        params.append(event_type)

    query += " ORDER BY id ASC"
    rows = conn.execute(query, params).fetchall()

    return [
        {
            "id": r[0],
            "event_type": r[1],
            "data": _json.loads(r[2]) if r[2] else {},
            "created_at": str(r[3]),
        }
        for r in rows
    ]


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


# --- Implementation plan helpers ---


def upsert_implementation_plan(
    consultation_id: str,
    plan_json: dict,
    markdown_path: str | None = None,
) -> None:
    """Insert or replace an implementation plan for a consultation."""
    import json as _json

    conn = get_connection()
    conn.execute(
        """INSERT OR REPLACE INTO implementation_plans
           (consultation_id, plan_json, markdown_path, created_at, updated_at)
           VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
        [consultation_id, _json.dumps(plan_json), markdown_path],
    )


def get_implementation_plan_record(consultation_id: str) -> dict | None:
    """Return an implementation plan record, or None if not found."""
    import json as _json

    conn = get_connection()
    row = conn.execute(
        "SELECT consultation_id, plan_json, markdown_path, created_at, updated_at FROM implementation_plans WHERE consultation_id = ?",
        [consultation_id],
    ).fetchone()
    if not row:
        return None
    return {
        "consultation_id": row[0],
        "plan_json": _json.loads(row[1]) if row[1] else {},
        "markdown_path": row[2],
        "created_at": str(row[3]),
        "updated_at": str(row[4]),
    }


def delete_implementation_plan(consultation_id: str) -> None:
    """Delete an implementation plan (for test cleanup)."""
    conn = get_connection()
    conn.execute(
        "DELETE FROM implementation_plans WHERE consultation_id = ?",
        [consultation_id],
    )


# --- Blackboard fact helpers ---


def assert_blackboard_fact(
    consultation_id: str,
    fact_type: str,
    key: str,
    value: object,
    confidence: float = 1.0,
    agent_id: str | None = None,
    ttl_seconds: int | None = None,
) -> int:
    """Append a fact to the blackboard (never overwrites). Returns the fact ID.

    Args:
        consultation_id: The consultation session.
        fact_type: Category of fact (e.g., 'concept_finding', 'pattern_assessment').
        key: Fact key (e.g., a concept ID or pattern ID).
        value: Arbitrary JSON-serializable value.
        confidence: Confidence score 0.0-1.0 (default 1.0).
        agent_id: Optional identifier of the subagent that asserted this fact.
        ttl_seconds: Optional time-to-live in seconds from now.
    """
    import json as _json
    from datetime import datetime, timezone, timedelta

    conn = get_connection()

    expires_at = None
    if ttl_seconds is not None:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)

    row = conn.execute(
        """INSERT INTO blackboard_facts
           (consultation_id, fact_type, key, value_json, confidence, agent_id, version, expires_at)
           VALUES (?, ?, ?, ?, ?, ?,
                   (SELECT COALESCE(MAX(version), 0) + 1
                    FROM blackboard_facts
                    WHERE consultation_id = ? AND key = ?
                      AND agent_id IS NOT DISTINCT FROM ?),
                   ?)
           RETURNING id""",
        [consultation_id, fact_type, key, _json.dumps(value), confidence,
         agent_id, consultation_id, key, agent_id, expires_at],
    ).fetchone()
    return row[0]


def query_blackboard_facts(
    consultation_id: str,
    fact_type: str | None = None,
    key: str | None = None,
    min_confidence: float | None = None,
    include_expired: bool = False,
) -> list[dict]:
    """Query facts from the blackboard.

    Args:
        consultation_id: The consultation session.
        fact_type: Filter by fact type (optional).
        key: Filter by key (optional).
        min_confidence: Minimum confidence threshold (optional).
        include_expired: Include facts past their TTL (default False).
    """
    import json as _json

    conn = get_connection()
    query = "SELECT id, fact_type, key, value_json, confidence, agent_id, version, expires_at, created_at FROM blackboard_facts WHERE consultation_id = ?"
    params: list = [consultation_id]

    if fact_type is not None:
        query += " AND fact_type = ?"
        params.append(fact_type)
    if key is not None:
        query += " AND key = ?"
        params.append(key)
    if min_confidence is not None:
        query += " AND confidence >= ?"
        params.append(min_confidence)
    if not include_expired:
        query += " AND (expires_at IS NULL OR expires_at > current_timestamp)"

    query += " ORDER BY created_at ASC"
    rows = conn.execute(query, params).fetchall()

    return [
        {
            "id": r[0],
            "fact_type": r[1],
            "key": r[2],
            "value": _json.loads(r[3]) if r[3] else None,
            "confidence": r[4],
            "agent_id": r[5],
            "version": r[6],
            "expires_at": str(r[7]) if r[7] else None,
            "created_at": str(r[8]),
        }
        for r in rows
    ]


def get_fact_conflicts(
    consultation_id: str,
    key: str,
) -> list[dict]:
    """Detect conflicting facts for a given key (different values from different agents).

    Returns groups of facts that have the same key but different values,
    each asserted by a different agent.
    """
    import json as _json

    conn = get_connection()
    # Get the latest version per agent for this key
    rows = conn.execute(
        """SELECT bf.id, bf.fact_type, bf.key, bf.value_json, bf.confidence,
                  bf.agent_id, bf.version, bf.created_at
           FROM blackboard_facts bf
           INNER JOIN (
               SELECT agent_id, MAX(version) as max_ver
               FROM blackboard_facts
               WHERE consultation_id = ? AND key = ?
                 AND (expires_at IS NULL OR expires_at > current_timestamp)
               GROUP BY agent_id
           ) latest ON bf.agent_id IS NOT DISTINCT FROM latest.agent_id
                    AND bf.version = latest.max_ver
           WHERE bf.consultation_id = ? AND bf.key = ?
             AND (bf.expires_at IS NULL OR bf.expires_at > current_timestamp)
           ORDER BY bf.confidence DESC""",
        [consultation_id, key, consultation_id, key],
    ).fetchall()

    facts = [
        {
            "id": r[0],
            "fact_type": r[1],
            "key": r[2],
            "value": _json.loads(r[3]) if r[3] else None,
            "confidence": r[4],
            "agent_id": r[5],
            "version": r[6],
            "created_at": str(r[7]),
        }
        for r in rows
    ]

    # Check if there are different values
    values_seen = set()
    for f in facts:
        values_seen.add(_json.dumps(f["value"], sort_keys=True))

    return facts if len(values_seen) > 1 else []


def get_convergence_status(
    consultation_id: str,
) -> dict:
    """Check how many facts have converged (single value) vs. conflicting.

    Returns:
        Dict with total_keys, converged_keys, conflicting_keys, and convergence_pct.
    """
    import json as _json

    conn = get_connection()
    # Get all unique keys
    keys = conn.execute(
        """SELECT DISTINCT key FROM blackboard_facts
           WHERE consultation_id = ?
             AND (expires_at IS NULL OR expires_at > current_timestamp)""",
        [consultation_id],
    ).fetchall()

    total_keys = len(keys)
    conflicting = 0

    for (key,) in keys:
        conflicts = get_fact_conflicts(consultation_id, key)
        if conflicts:
            conflicting += 1

    converged = total_keys - conflicting
    pct = int((converged / total_keys) * 100) if total_keys > 0 else 100

    return {
        "total_keys": total_keys,
        "converged_keys": converged,
        "conflicting_keys": conflicting,
        "convergence_pct": pct,
    }


# --- Consultation quality helpers ---


def insert_quality_rating(
    consultation_id: str,
    rating: int | None = None,
    feedback: str | None = None,
    concept_coverage: float | None = None,
    pattern_count: int | None = None,
    maturity_level: int | None = None,
) -> int:
    """Insert a quality rating for a consultation. Returns the record ID."""
    conn = get_connection()
    row = conn.execute(
        """INSERT INTO consultation_quality
           (consultation_id, rating, feedback, concept_coverage, pattern_count, maturity_level)
           VALUES (?, ?, ?, ?, ?, ?)
           RETURNING id""",
        [consultation_id, rating, feedback, concept_coverage, pattern_count, maturity_level],
    ).fetchone()
    return row[0]


def get_quality_ratings(limit: int = 20) -> list[dict]:
    """Get recent quality ratings across consultations."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT id, consultation_id, rating, feedback, concept_coverage,
                  pattern_count, maturity_level, created_at
           FROM consultation_quality
           ORDER BY created_at DESC
           LIMIT ?""",
        [limit],
    ).fetchall()
    return [
        {
            "id": r[0],
            "consultation_id": r[1],
            "rating": r[2],
            "feedback": r[3],
            "concept_coverage": r[4],
            "pattern_count": r[5],
            "maturity_level": r[6],
            "created_at": str(r[7]),
        }
        for r in rows
    ]
