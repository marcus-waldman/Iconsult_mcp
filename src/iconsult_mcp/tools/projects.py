"""Phase 3 — project / per-project canonical layer tools.

Stage 3a ships `list_books` (corpus introspection). Stage 3b will add
`start_project`; stage 3c will add `build_project_kg`. Keeping all three in
one module so the per-project layer's MCP surface stays cohesive.
"""

from __future__ import annotations

from iconsult_mcp.db import list_books as db_list_books


async def list_books(altitude: str | None = None) -> dict:
    """Return all registered books, optionally filtered by altitude.

    Args:
        altitude: Optional altitude filter ('mid_level', 'implementation',
            'strategy', 'domain'). When None, returns every book.

    Pure read tool; deterministic; no consultation_id created.
    """
    rows = db_list_books(altitude=altitude)
    return {
        "books": rows,
        "total": len(rows),
        "altitude_filter": altitude,
    }
