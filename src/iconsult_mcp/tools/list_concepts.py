"""List concepts in the knowledge graph (compact by default)."""

from iconsult_mcp.db import get_all_concepts


async def list_concepts(
    search: str | None = None,
    include_definitions: bool = False,
) -> dict:
    """Return concepts as a flat list (compact by default).

    Args:
        search: Filter by name substring (case-insensitive).
        include_definitions: Include definition text (default: False).
    """
    concepts = get_all_concepts(
        include_definitions=include_definitions,
        search=search,
    )
    return {"total": len(concepts), "concepts": concepts}
