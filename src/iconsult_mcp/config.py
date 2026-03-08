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
MOTHERDUCK_SHARE_URL = "_share/Iconsult_share/793b6b5a-8eb3-4b0d-bb04-94542d6303a2"

# Embeddings
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536

# Tool execution
TOOL_TIMEOUT_SECONDS = 30
TOOL_MAX_RETRIES = 2
TOOL_RETRY_BASE_DELAY = 1.0

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LITERATURE_DIR = PROJECT_ROOT / "literature"
BOOK_FILENAME = "Arsanjani and Bustos - 2026 - Agentic architectural patterns for building multi-agent systems proven.md"
INDEX_FILENAME = "Arsanjani and Bustos - INDEX.md"
