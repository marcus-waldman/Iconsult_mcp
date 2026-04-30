"""Phase 3 — project / per-project canonical layer tools.

Stage 3a ships `list_books` (corpus introspection). Stage 3b adds
`start_project`. Stage 3c will add `build_project_kg`. Keeping all three in
one module so the per-project layer's MCP surface stays cohesive.
"""

from __future__ import annotations

import hashlib

from iconsult_mcp.db import (
    create_project,
    get_project,
    list_books as db_list_books,
)
from iconsult_mcp.tools.triage import triage_books


def _derive_project_id(name: str, project_description: str) -> str:
    """Deterministic project ID derived from (name, description).

    Same input always produces the same ID — calling `start_project` twice
    with the same args returns the existing project rather than creating a
    duplicate.
    """
    digest = hashlib.sha256(
        f"{name}\n{project_description}".encode("utf-8")
    ).hexdigest()
    return f"proj_{digest[:12]}"


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


async def start_project(
    name: str,
    project_description: str,
    triaged_book_ids: list[str] | None = None,
    project_id: str | None = None,
    triage_top_k: int = 5,
    triage_threshold: float = 0.4,
) -> dict:
    """Create or refresh a per-project cache row.

    Args:
        name: Human-readable project name.
        project_description: Free-text description used as the triage signal
            (and as the canonical text input for `build_project_kg` later).
        triaged_book_ids: Explicit book IDs to scope the project to. When
            omitted, `triage_books` runs internally with the same description
            and the resulting ranked IDs are stored.
        project_id: Optional user-supplied ID. When omitted, a deterministic
            ID is derived from (name, project_description) so calling this
            tool twice with the same args is idempotent.
        triage_top_k: Top-k for the internal triage call (default 5).
        triage_threshold: Cosine threshold for internal triage (default 0.4,
            matching `triage_books`). Books below threshold are excluded.

    Returns:
        Dict with `project_id`, `project` (full row), and `triage` details
        (the internal triage result when one ran, or `None` when explicit
        IDs were provided).

    Notes:
        - Does NOT build the unified KG — that is `build_project_kg` (3c).
          A freshly-created project always has `unified_kg_built_at = None`.
        - When triage returns no books above threshold, the project is still
          created with `triaged_book_ids = []`. `build_project_kg` will
          refuse to run on a zero-book project.
    """
    if not name or not name.strip():
        return {"error": "name must be a non-empty string"}
    if not project_description or not project_description.strip():
        return {"error": "project_description must be a non-empty string"}

    name = name.strip()
    project_description = project_description.strip()

    pid = project_id or _derive_project_id(name, project_description)

    triage_result: dict | None = None
    if triaged_book_ids is None:
        triage_result = await triage_books(
            project_description=project_description,
            top_k=triage_top_k,
            threshold=triage_threshold,
        )
        if "error" in triage_result:
            return {"error": f"internal triage failed: {triage_result['error']}"}
        resolved_book_ids = [b["id"] for b in triage_result.get("ranked_books", [])]
    else:
        if not isinstance(triaged_book_ids, list) or not all(
            isinstance(x, str) for x in triaged_book_ids
        ):
            return {"error": "triaged_book_ids must be a list of book ID strings"}
        resolved_book_ids = list(triaged_book_ids)

    create_project(
        project_id=pid,
        name=name,
        description=project_description,
        triaged_book_ids=resolved_book_ids,
    )

    project_row = get_project(pid)
    return {
        "project_id": pid,
        "project": project_row,
        "triage": triage_result,
    }
