"""
Configuration for iconsult-mcp.

Reads settings from environment variables with sensible defaults.
"""

import os
from pathlib import Path


def get_motherduck_token() -> str | None:
    return os.environ.get("MOTHERDUCK_TOKEN")


def get_openai_api_key() -> str | None:
    return os.environ.get("OPENAI_API_KEY")


def get_anthropic_api_key() -> str | None:
    return os.environ.get("ANTHROPIC_API_KEY")


# Database
MOTHERDUCK_DATABASE = os.environ.get("ICONSULT_DB", "Iconsult")

# Embeddings
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LITERATURE_DIR = PROJECT_ROOT / "literature"
BOOK_FILENAME = "Arsanjani and Bustos - 2026 - Agentic architectural patterns for building multi-agent systems proven.md"
INDEX_FILENAME = "Arsanjani and Bustos - INDEX.md"
