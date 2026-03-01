"""List all concepts in the knowledge graph, grouped by category."""

from iconsult_mcp.db import get_all_concepts


async def list_concepts() -> dict:
    """Return all concepts grouped by category."""
    concepts = get_all_concepts()

    by_category: dict[str, list[dict]] = {}
    for c in concepts:
        cat = c["category"] if c["category"] else "uncategorized"
        by_category.setdefault(cat, []).append({
            "id": c["id"],
            "name": c["name"],
            "definition": c["definition"],
        })

    return {
        "total": len(concepts),
        "categories": {
            cat: {"count": len(items), "concepts": items}
            for cat, items in sorted(by_category.items())
        },
    }
