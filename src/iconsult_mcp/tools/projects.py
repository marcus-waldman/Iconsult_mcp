"""Phase 3 — project / per-project canonical layer tools.

Stage 3a ships `list_books` (corpus introspection). Stage 3b adds
`start_project`. Stage 3c adds `build_project_kg` (alignment + clustering
into canonical_concepts). Keeping all three in one module so the per-
project layer's MCP surface stays cohesive.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import sys
from pathlib import Path

from iconsult_mcp.config import EMBEDDING_DIMENSIONS
from iconsult_mcp.db import (
    create_project,
    get_book,
    get_connection,
    get_project,
    list_books as db_list_books,
    list_canonical_concepts,
    mark_project_kg_built,
    upsert_canonical_concept,
)
from iconsult_mcp.tools.rubric_data import ALL_PATTERN_IDS, normalize_pattern_id
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


# --- 3c: build_project_kg ---------------------------------------------------


def _slugify(name: str, limit: int = 60) -> str:
    """Bare slug for canonical concept IDs (mirrors parse_index.slugify)."""
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = s.strip("_")
    return s[:limit] if len(s) > limit else s


class _UnionFind:
    """Tiny union-find for concept-cluster building."""

    def __init__(self, items):
        self._parent = {x: x for x in items}

    def find(self, x: str) -> str:
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]  # path compression
            x = self._parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[ra] = rb

    def clusters(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for x in self._parent:
            r = self.find(x)
            out.setdefault(r, []).append(x)
        return out


def _fetch_book_concepts_with_embeddings(book_ids: list[str]) -> dict[str, dict]:
    """Return {concept_id: {name, book_id, embedding}} for the given books.

    Concepts without an embedding are skipped (Phase 4's `build_graph`
    embeds every concept, so this should be empty in practice).
    """
    conn = get_connection()
    placeholders = ", ".join("?" for _ in book_ids)
    rows = conn.execute(
        f"""
        SELECT c.id, c.name, c.book_id, ce.embedding
        FROM concepts c
        JOIN concept_embeddings ce ON ce.concept_id = c.id
        WHERE c.book_id IN ({placeholders})
        """,
        book_ids,
    ).fetchall()
    out: dict[str, dict] = {}
    for r in rows:
        out[r[0]] = {
            "id": r[0],
            "name": r[1],
            "book_id": r[2],
            "embedding": list(r[3]),
        }
    return out


def _fetch_positive_verdicts_for_books(book_ids: list[str]) -> list[tuple[str, str]]:
    """Return (a_id, b_id) tuples where same_concept=True and both concepts
    belong to one of the project's books."""
    if len(book_ids) < 2:
        return []
    conn = get_connection()
    placeholders = ", ".join("?" for _ in book_ids)
    rows = conn.execute(
        f"""
        SELECT cac.concept_a_id, cac.concept_b_id
        FROM concept_alignment_cache cac
        JOIN concepts ca ON cac.concept_a_id = ca.id
        JOIN concepts cb ON cac.concept_b_id = cb.id
        WHERE cac.same_concept = TRUE
          AND ca.book_id IN ({placeholders})
          AND cb.book_id IN ({placeholders})
        """,
        list(book_ids) + list(book_ids),
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def _mean_embedding(vectors: list[list[float]]) -> list[float]:
    """Element-wise mean of equal-length float vectors."""
    if not vectors:
        return [0.0] * EMBEDDING_DIMENSIONS
    n = len(vectors)
    dim = len(vectors[0])
    out = [0.0] * dim
    for v in vectors:
        for i, x in enumerate(v):
            out[i] += x
    return [x / n for x in out]


def _classify_cluster_role(
    member_ids: list[str],
) -> tuple[str, str | None]:
    """Decide role + rubric_pattern_id for a cluster.

    Any member whose normalized ID hits the rubric pattern set anchors the
    cluster as `supporting_evidence` — these are the cross-book concepts
    that flow into score_architecture via the existing alias machinery.
    """
    for mid in member_ids:
        canonical = normalize_pattern_id(mid)
        if canonical in ALL_PATTERN_IDS:
            return "supporting_evidence", canonical
    return "informational_only", None


def _pick_canonical_name(
    member_ids: list[str],
    concept_index: dict[str, dict],
    oracle_book_id: str | None,
) -> str:
    """Pick a representative cluster name. Prefer the oracle book's name when
    a member belongs to it (the rubric is anchored there); otherwise the
    shortest member name (proxy for "least decorated"); ties broken
    alphabetically for determinism."""
    members = [concept_index[m] for m in member_ids if m in concept_index]
    if not members:
        return "(unknown cluster)"

    if oracle_book_id:
        oracle_members = [m for m in members if m["book_id"] == oracle_book_id]
        if oracle_members:
            return sorted(oracle_members, key=lambda m: (len(m["name"]), m["name"]))[0]["name"]

    return sorted(members, key=lambda m: (len(m["name"]), m["name"]))[0]["name"]


def _resolve_oracle_book(book_ids: list[str]) -> str | None:
    """Return the project's oracle book id (if any). Used to prefer oracle
    naming for canonical clusters and to keep rubric anchoring obvious."""
    for bid in book_ids:
        row = get_book(bid)
        if row and row.get("is_oracle"):
            return bid
    return None


async def build_project_kg(
    project_id: str,
    force: bool = False,
    auto_align: bool = True,
    align_threshold: float = 0.6,
    align_top_k: int = 5,
) -> dict:
    """Build the per-project canonical layer.

    Reads positive verdicts from `concept_alignment_cache`, runs union-find
    over the project's concepts, writes one `canonical_concepts` row per
    cluster (singletons included) with role + rubric_pattern_id +
    canonical_embedding, marks the project as built.

    Args:
        project_id: The project to build a canonical KG for.
        force: When True, rebuild even if `unified_kg_built_at` is set
            (existing canonical_concepts for this project are replaced).
        auto_align: When True (default), call `align_book_pair` for any
            project book pair before clustering. Cached pairs are no-ops, so
            this is cheap on re-runs but ensures the cache is populated for
            new pairs.
        align_threshold, align_top_k: Forwarded to `align_book_pair` when
            `auto_align` is True.

    Returns dict with stats + a small preview sample of canonical clusters.
    """
    project = get_project(project_id)
    if project is None:
        return {"error": f"project '{project_id}' not found"}

    book_ids: list[str] = list(project.get("triaged_book_ids") or [])
    if not book_ids:
        return {
            "error": (
                f"project '{project_id}' has no triaged_book_ids; "
                "build_project_kg requires at least one book in the project"
            )
        }

    if project.get("unified_kg_built_at") and not force:
        return {
            "project_id": project_id,
            "skipped": True,
            "reason": (
                "project's unified KG already built at "
                f"{project['unified_kg_built_at']}; pass force=True to rebuild"
            ),
            "unified_kg_built_at": project["unified_kg_built_at"],
        }

    # Ensure alignment cache is warm for every project book pair. Pairs already
    # cached are skipped inside align_book_pair, so this is a no-op for
    # pre-warmed corpora.
    align_summary: list[dict] = []
    if auto_align and len(book_ids) >= 2:
        # Lazy import: align_book_pair lives under scripts/, not the package
        scripts_dir = str(Path(__file__).resolve().parents[3] / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from align_book_pair import align_book_pair as _align_pair  # type: ignore

        ordered = sorted(book_ids)
        for i, a in enumerate(ordered):
            for b in ordered[i + 1 :]:
                summary = await _align_pair(
                    book_a_id=a,
                    book_b_id=b,
                    threshold=align_threshold,
                    top_k_per_side=align_top_k,
                    verbose=False,
                )
                align_summary.append({
                    "pair": (a, b),
                    "shortlisted": summary["shortlisted"],
                    "cached_hits": summary["cached_hits"],
                    "adjudicated": summary["adjudicated"],
                    "same_count": summary["same_count"],
                })

    # Fetch all concepts (with embeddings) for the project's books.
    concept_index = _fetch_book_concepts_with_embeddings(book_ids)
    if not concept_index:
        return {
            "error": (
                f"project '{project_id}' books have no concepts with "
                "embeddings — has the pipeline run for these books?"
            )
        }

    # Union-find over positive alignment verdicts.
    uf = _UnionFind(list(concept_index.keys()))
    verdicts = _fetch_positive_verdicts_for_books(book_ids)
    for a, b in verdicts:
        if a in concept_index and b in concept_index:
            uf.union(a, b)
    clusters = uf.clusters()

    oracle_book = _resolve_oracle_book(book_ids)

    # If force=True, clear existing canonical_concepts for this project so
    # stale clusters don't accumulate. (canonical_concepts.id is project-
    # prefixed so this DELETE is scoped tightly.)
    if force:
        conn = get_connection()
        conn.execute(
            "DELETE FROM canonical_concepts WHERE project_id = ?",
            [project_id],
        )

    role_counts = {"supporting_evidence": 0, "informational_only": 0}
    multi_member_clusters: list[dict] = []
    seen_canonical_ids: set[str] = set()

    for _root, members in clusters.items():
        member_ids = sorted(members)  # deterministic
        canonical_name = _pick_canonical_name(member_ids, concept_index, oracle_book)
        role, rubric_pid = _classify_cluster_role(member_ids)

        slug = _slugify(canonical_name)
        canonical_id = f"{project_id}__{slug}"
        # Disambiguate slug collisions deterministically
        suffix = 2
        while canonical_id in seen_canonical_ids:
            canonical_id = f"{project_id}__{slug}_{suffix}"
            suffix += 1
        seen_canonical_ids.add(canonical_id)

        embeddings = [concept_index[m]["embedding"] for m in member_ids]
        canonical_embedding = _mean_embedding(embeddings)

        upsert_canonical_concept(
            canonical_id=canonical_id,
            project_id=project_id,
            name=canonical_name,
            member_concept_ids=member_ids,
            role=role,
            rubric_pattern_id=rubric_pid,
            canonical_embedding=canonical_embedding,
        )

        role_counts[role] += 1

        if len(member_ids) >= 2:
            multi_member_clusters.append({
                "canonical_id": canonical_id,
                "name": canonical_name,
                "role": role,
                "rubric_pattern_id": rubric_pid,
                "member_count": len(member_ids),
                "member_books": sorted({
                    concept_index[m]["book_id"] for m in member_ids
                }),
                "members": [
                    {"id": m, "name": concept_index[m]["name"], "book_id": concept_index[m]["book_id"]}
                    for m in member_ids
                ],
            })

    mark_project_kg_built(project_id)

    # Sort multi-member clusters: supporting evidence first, then by member count desc.
    multi_member_clusters.sort(
        key=lambda c: (0 if c["role"] == "supporting_evidence" else 1, -c["member_count"], c["name"])
    )

    return {
        "project_id": project_id,
        "skipped": False,
        "books": book_ids,
        "concepts_total": len(concept_index),
        "clusters_total": len(clusters),
        "clusters_multi_member": len(multi_member_clusters),
        "clusters_singleton": len(clusters) - len(multi_member_clusters),
        "by_role": role_counts,
        "alignment": align_summary,
        "preview_clusters": multi_member_clusters[:20],
    }
