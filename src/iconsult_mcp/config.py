"""
Configuration for iconsult-mcp.

Reads settings from environment variables with sensible defaults.
"""

import os
from pathlib import Path


def get_motherduck_token() -> str | None:
    """Deprecated. Retained as a no-op shim during the multi-book refactor.

    The runtime database is now local DuckDB; MotherDuck is not the deployment
    target for this codebase. See docs/multi-book-architecture-plan.md.
    """
    return os.environ.get("MOTHERDUCK_TOKEN")


def get_openai_api_key() -> str | None:
    return os.environ.get("OPENAI_API_KEY")


def get_anthropic_api_key() -> str | None:
    return os.environ.get("ANTHROPIC_API_KEY")


# --- Paths -------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LITERATURE_DIR = PROJECT_ROOT / "literature"


# --- Books registry ---------------------------------------------------------
#
# Source of truth for ingested book metadata and on-disk file paths.
# Each book lives under `literature/{subdir}/{book_filename, index_filename}`.
#
# Multi-book refactor, Phase 1b. Phase 1c will switch the per-book scripts
# (parse_book, parse_index, tag_concepts, discover_relationships,
# populate_content) from the BOOK_FILENAME / INDEX_FILENAME shim constants
# below to the get_book_paths(book_id) helper.

BOOKS: dict[str, dict] = {
    "arsanjani_2026": {
        "title": "Agentic Architectural Patterns for Building Multi-Agent Systems Proven",
        "authors": "Arsanjani & Bustos",
        "year": 2026,
        "altitude": "mid_level",
        "is_oracle": True,
        "subdir": "arsanjani_2026",
        "book_filename": "Arsanjani and Bustos - 2026 - Agentic architectural patterns for building multi-agent systems proven.md",
        "index_filename": "Arsanjani and Bustos - INDEX.md",
    },
    "gulli_2025": {
        "title": "Agentic Design Patterns: A Hands-On Guide to Building Intelligent Systems",
        "authors": "Antonio Gulli",
        "year": 2025,
        "altitude": "implementation",
        "is_oracle": False,
        "subdir": "gulli_2025",
        "book_filename": "Gulli - 2025- Agentic Design Patterns A Hands-On Guide to Building.md",
        # Synthesized page-numbered index (chapter-ref → chapter-start-page).
        # Source `Gulli - 2025 - INDEX.md` is preserved alongside it.
        # Regenerate via `py scripts/synthesize_gulli_index.py`.
        "index_filename": "Gulli - 2025 - INDEX-page-numbered.md",
    },
}


def get_book_paths(book_id: str) -> dict[str, Path]:
    """Resolve absolute on-disk paths for a registered book."""
    if book_id not in BOOKS:
        raise KeyError(
            f"Unknown book_id '{book_id}'. Registered: {sorted(BOOKS.keys())}"
        )
    meta = BOOKS[book_id]
    base = LITERATURE_DIR / meta["subdir"]
    return {
        "base": base,
        "book": base / meta["book_filename"],
        "index": base / meta["index_filename"],
    }


def get_book_metadata(book_id: str) -> dict:
    """Return the full metadata dict for a registered book."""
    if book_id not in BOOKS:
        raise KeyError(
            f"Unknown book_id '{book_id}'. Registered: {sorted(BOOKS.keys())}"
        )
    return dict(BOOKS[book_id])  # shallow copy so callers can mutate safely


def list_registered_books() -> list[str]:
    """Return the registered book_ids in insertion order."""
    return list(BOOKS.keys())


# Backward-compat shims. Existing scripts use:
#     book_path = LITERATURE_DIR / BOOK_FILENAME
# These constants embed the per-book subdir so that pattern keeps resolving
# correctly to the new on-disk layout. Phase 1c will replace call sites with
# `get_book_paths(book_id)["book"]` and similar, then these constants can be
# deleted.
_DEFAULT_BOOK_ID = "arsanjani_2026"
_default_meta = BOOKS[_DEFAULT_BOOK_ID]
BOOK_FILENAME = f"{_default_meta['subdir']}/{_default_meta['book_filename']}"
INDEX_FILENAME = f"{_default_meta['subdir']}/{_default_meta['index_filename']}"


# --- Database ----------------------------------------------------------------
# Local DuckDB only. The `ICONSULT_DB` env var may be:
#   * an absolute filesystem path (preferred for production / dev sandboxes)
#   * a relative path interpreted against PROJECT_ROOT (handy for tests)
#   * the literal ":memory:" for ephemeral/in-memory databases
#
# Defaults to PROJECT_ROOT/data/iconsult.duckdb. The `data/` directory is
# already gitignored.
#
# MotherDuck-style identifiers (e.g., "Iconsult", "md:..." URLs) are no longer
# accepted; see docs/multi-book-architecture-plan.md for the rationale.

DEFAULT_DB_FILENAME = "iconsult.duckdb"
DEFAULT_DB_DIR = PROJECT_ROOT / "data"


def get_db_path() -> str:
    """Resolve the local DuckDB path from `ICONSULT_DB` or the default."""
    raw = os.environ.get("ICONSULT_DB")
    if not raw:
        DEFAULT_DB_DIR.mkdir(parents=True, exist_ok=True)
        return str(DEFAULT_DB_DIR / DEFAULT_DB_FILENAME)
    if raw == ":memory:":
        return raw
    p = Path(raw)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    p.parent.mkdir(parents=True, exist_ok=True)
    return str(p)


# --- Embeddings --------------------------------------------------------------

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536


# --- Tool execution ----------------------------------------------------------

TOOL_TIMEOUT_SECONDS = 30
TOOL_MAX_RETRIES = 2
TOOL_RETRY_BASE_DELAY = 1.0
