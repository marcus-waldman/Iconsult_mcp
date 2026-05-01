"""Phase 3c — adjudicate concept-pair alignment between two books.

Shortlists cross-book concept pairs by cosine similarity (threshold + per-
side top-k), reads existing verdicts from `concept_alignment_cache`, batches
un-cached pairs to Claude for "same concept?" adjudication, persists
verdicts back to the cache. Cache rows are stored in canonical pair order
(`a_id < b_id`) so the same pair is never adjudicated twice from a
different direction.

Reusable: `align_book_pair(...)` is callable from `build_project_kg`
(Phase 3c.2). Standalone runnable to pre-warm the cache for a book pair:

    py scripts/align_book_pair.py --book-a arsanjani_2026 --book-b gulli_2025

Idempotent. Re-running is a no-op when every shortlisted pair is already
cached. `--force` ignores the cache and re-adjudicates every shortlisted
pair (overwrites verdicts).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from iconsult_mcp.config import EMBEDDING_DIMENSIONS  # noqa: E402
from iconsult_mcp.db import (  # noqa: E402
    close_connection,
    get_alignment_decision,
    get_connection,
    record_alignment_decision,
)
from iconsult_mcp.embed import claude_messages  # noqa: E402

logger = logging.getLogger(__name__)


# Adjudication tuning. Defaults are conservative — feel free to widen for a
# pre-warm run, then re-run with the cache populated for fast subsequent
# project builds.
DEFAULT_SHORTLIST_THRESHOLD = 0.6  # cosine cut for candidate pairs
DEFAULT_TOP_K_PER_SIDE = 5  # bidirectional top-k cap; shortlist = union
DEFAULT_BATCH_SIZE = 12  # pairs per Claude call

# Sonnet 4 is the established adjudication model in this codebase
# (see embed.claude_messages default).
ADJUDICATION_MODEL = "claude-sonnet-4-20250514"


def shortlist_cross_book_pairs(
    book_a_id: str,
    book_b_id: str,
    threshold: float = DEFAULT_SHORTLIST_THRESHOLD,
    top_k_per_side: int = DEFAULT_TOP_K_PER_SIDE,
) -> list[dict]:
    """Return cross-book concept pairs that exceed the cosine threshold and
    are in either book's per-side top-k. Bidirectional coverage handles the
    asymmetric case where two A concepts both look most-like one B concept.

    Pair ordering in the returned dicts is whatever the SQL produced; callers
    should normalise via `_canonical_pair` (or `record_alignment_decision`
    which does so internally) before reading/writing the cache.
    """
    conn = get_connection()
    sql = f"""
        WITH pairs_scored AS (
            SELECT
                ca.id AS a_id, ca.name AS a_name, ca.definition AS a_def,
                cb.id AS b_id, cb.name AS b_name, cb.definition AS b_def,
                array_cosine_similarity(
                    cea.embedding::FLOAT[{EMBEDDING_DIMENSIONS}],
                    ceb.embedding::FLOAT[{EMBEDDING_DIMENSIONS}]
                ) AS score
            FROM concepts ca
            JOIN concept_embeddings cea ON ca.id = cea.concept_id
            CROSS JOIN concepts cb
            JOIN concept_embeddings ceb ON cb.id = ceb.concept_id
            WHERE ca.book_id = ?
              AND cb.book_id = ?
        ),
        ranked AS (
            SELECT *,
                ROW_NUMBER() OVER (PARTITION BY a_id ORDER BY score DESC) AS rank_a,
                ROW_NUMBER() OVER (PARTITION BY b_id ORDER BY score DESC) AS rank_b
            FROM pairs_scored
            WHERE score >= ?
        )
        SELECT a_id, a_name, a_def, b_id, b_name, b_def, score
        FROM ranked
        WHERE rank_a <= ? OR rank_b <= ?
        ORDER BY score DESC
    """
    rows = conn.execute(
        sql,
        [book_a_id, book_b_id, threshold, top_k_per_side, top_k_per_side],
    ).fetchall()

    return [
        {
            "a_id": r[0],
            "a_name": r[1],
            "a_def": r[2] or "(no definition recorded)",
            "b_id": r[3],
            "b_name": r[4],
            "b_def": r[5] or "(no definition recorded)",
            "score": float(r[6]),
        }
        for r in rows
    ]


def _truncate_def(text: str, limit: int = 320) -> str:
    """Trim long definitions for prompt economy without losing the first
    sentence. Replace whitespace runs to keep the prompt compact."""
    if text is None:
        return "(no definition recorded)"
    text = re.sub(r"\s+", " ", text.strip())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


_ADJUDICATION_SYSTEM = (
    "You decide whether pairs of concepts from two different books refer to "
    "the SAME concept. Books may use different vocabulary, or frame the same "
    "pattern at different altitudes (one architectural, one implementation-"
    "focused). Two concepts are the SAME if they describe the same essential "
    "idea or pattern, even if the terminology differs. They are NOT the same "
    "if they merely co-occur, share a parent category, or address related "
    "but distinct problems. Be willing to say `false` — false alignments "
    "pollute the canonical layer downstream."
)


def _build_adjudication_prompt(batch: list[dict]) -> str:
    lines = [
        "Decide for each pair below whether the two concepts are the same.",
        "Respond with a JSON array, one object per pair, same order:",
        '  [{"a_id": "...", "b_id": "...", "same_concept": bool, '
        '"confidence": float in [0,1], "rationale": "one short sentence"}]',
        "Return ONLY the JSON array — no prose, no code fences.",
        "",
        "Pairs:",
    ]
    for i, p in enumerate(batch, start=1):
        lines.append(
            f"\n{i}. A.id: {p['a_id']}\n"
            f"   A.name: {p['a_name']}\n"
            f"   A.definition: {_truncate_def(p['a_def'])}\n"
            f"   B.id: {p['b_id']}\n"
            f"   B.name: {p['b_name']}\n"
            f"   B.definition: {_truncate_def(p['b_def'])}\n"
            f"   embedding_cosine: {p['score']:.3f}"
        )
    return "\n".join(lines)


def _parse_adjudication_response(response: str, batch: list[dict]) -> list[dict]:
    """Parse Claude's JSON array. Tolerates accidental code fences."""
    text = response.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    parsed = json.loads(text)
    if not isinstance(parsed, list):
        raise ValueError(f"expected a JSON array, got {type(parsed).__name__}")
    if len(parsed) != len(batch):
        raise ValueError(
            f"length mismatch: model returned {len(parsed)} verdicts for "
            f"{len(batch)} pairs"
        )
    out = []
    for verdict, pair in zip(parsed, batch):
        # Be tolerant about which IDs the model echoed back; trust positional
        # order. (We tell it to keep the order.)
        out.append({
            "a_id": pair["a_id"],
            "b_id": pair["b_id"],
            "same_concept": bool(verdict.get("same_concept", False)),
            "confidence": float(verdict.get("confidence", 0.0)),
            "rationale": str(verdict.get("rationale", ""))[:400],
        })
    return out


async def adjudicate_batch(batch: list[dict]) -> list[dict]:
    """Send one batch of pairs to Claude. Returns verdicts in the same order."""
    prompt = _build_adjudication_prompt(batch)
    response = await claude_messages(
        messages=[{"role": "user", "content": prompt}],
        system=_ADJUDICATION_SYSTEM,
        model=ADJUDICATION_MODEL,
        max_tokens=4096,
    )
    return _parse_adjudication_response(response, batch)


async def align_book_pair(
    book_a_id: str,
    book_b_id: str,
    threshold: float = DEFAULT_SHORTLIST_THRESHOLD,
    top_k_per_side: int = DEFAULT_TOP_K_PER_SIDE,
    batch_size: int = DEFAULT_BATCH_SIZE,
    force: bool = False,
    verbose: bool = True,
) -> dict:
    """Adjudicate cross-book concept pairs and persist verdicts.

    Args:
        book_a_id, book_b_id: Book IDs (any order; pairs stored in canonical
            lex order via `_canonical_pair`).
        threshold: Cosine cut for shortlisting candidate pairs.
        top_k_per_side: Per-side top-k cap for bidirectional coverage.
        batch_size: Pairs per Claude call.
        force: When True, re-adjudicate even already-cached pairs.
        verbose: Progress printing.

    Returns:
        Dict with `shortlisted` / `cached_hits` / `adjudicated` / `same_count`
        / `pairs` (the verdicts from this run; existing cache hits NOT
        replayed unless `force=True`).
    """
    if book_a_id == book_b_id:
        raise ValueError("book_a_id and book_b_id must differ")

    pairs = shortlist_cross_book_pairs(
        book_a_id, book_b_id,
        threshold=threshold,
        top_k_per_side=top_k_per_side,
    )

    if verbose:
        print(
            f"Shortlisted {len(pairs)} pairs above cosine {threshold} "
            f"(top-{top_k_per_side} per side) for ({book_a_id}, {book_b_id})."
        )

    # Filter to pairs we still need to adjudicate.
    todo: list[dict] = []
    cached_hits = 0
    for p in pairs:
        if not force:
            cached = get_alignment_decision(p["a_id"], p["b_id"])
            if cached is not None:
                cached_hits += 1
                continue
        todo.append(p)

    if verbose:
        print(
            f"Cache hits: {cached_hits}. To adjudicate: {len(todo)}."
        )

    verdicts: list[dict] = []
    n_batches = (len(todo) + batch_size - 1) // batch_size
    for i in range(0, len(todo), batch_size):
        batch = todo[i : i + batch_size]
        batch_idx = i // batch_size + 1
        if verbose:
            print(f"  Adjudication batch {batch_idx}/{n_batches} "
                  f"({len(batch)} pairs)...")
        try:
            batch_verdicts = await adjudicate_batch(batch)
        except Exception as e:
            print(
                f"  Warning: batch {batch_idx} failed ({type(e).__name__}: {e}); "
                f"skipping these {len(batch)} pairs (they remain un-cached "
                f"and a re-run will retry)."
            )
            continue
        for v in batch_verdicts:
            record_alignment_decision(
                concept_a_id=v["a_id"],
                concept_b_id=v["b_id"],
                same_concept=v["same_concept"],
                confidence=v["confidence"],
                rationale=v["rationale"],
            )
            verdicts.append(v)

    same_count = sum(1 for v in verdicts if v["same_concept"])
    if verbose:
        print(
            f"Adjudicated {len(verdicts)} pairs; "
            f"{same_count} verdicts of same_concept=True."
        )

    return {
        "book_a_id": book_a_id,
        "book_b_id": book_b_id,
        "shortlisted": len(pairs),
        "cached_hits": cached_hits,
        "adjudicated": len(verdicts),
        "same_count": same_count,
        "verdicts": verdicts,
    }


async def main() -> int:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--book-a", required=True, help="First book ID")
    parser.add_argument("--book-b", required=True, help="Second book ID")
    parser.add_argument(
        "--threshold", type=float, default=DEFAULT_SHORTLIST_THRESHOLD,
        help=f"Cosine threshold for shortlisting (default {DEFAULT_SHORTLIST_THRESHOLD})",
    )
    parser.add_argument(
        "--top-k", type=int, default=DEFAULT_TOP_K_PER_SIDE,
        help=f"Per-side top-k for bidirectional coverage (default {DEFAULT_TOP_K_PER_SIDE})",
    )
    parser.add_argument(
        "--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
        help=f"Pairs per Claude call (default {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-adjudicate pairs already in concept_alignment_cache",
    )
    args = parser.parse_args()

    summary = await align_book_pair(
        book_a_id=args.book_a,
        book_b_id=args.book_b,
        threshold=args.threshold,
        top_k_per_side=args.top_k,
        batch_size=args.batch_size,
        force=args.force,
        verbose=True,
    )

    print()
    print("=== Summary ===")
    print(f"  Book pair: ({summary['book_a_id']}, {summary['book_b_id']})")
    print(f"  Shortlisted pairs: {summary['shortlisted']}")
    print(f"  Cache hits (skipped): {summary['cached_hits']}")
    print(f"  Newly adjudicated: {summary['adjudicated']}")
    print(f"  same_concept=True: {summary['same_count']}")

    close_connection()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
