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
BOOK_FILENAME = "Arsanjani and Bustos - 2026 - Agentic architectural patterns for building multi-agent systems proven.md"
INDEX_FILENAME = "Arsanjani and Bustos - INDEX.md"


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
