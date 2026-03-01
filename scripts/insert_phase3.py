"""
Helper script for Phase 3 insertion.

Inserts relationship data into the relationships table.

Usage:
    py scripts/insert_phase3.py data/phase3_ch01_04.json --label ch01_04
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from iconsult_mcp.db import get_connection


def insert_relationships(rels: list[dict], dry_run: bool = False) -> dict:
    """Insert relationships into the database.

    Each relationship should have:
        from_concept_id: str
        to_concept_id: str
        relationship_type: str (uses, extends, alternative_to, component_of, requires, conflicts_with, specializes, precedes)
        confidence: float (0.0-1.0)
        source_type: str ("explicit" or "semantic")
        description: str
        provenance_sections: list[str] (section IDs)
        provenance_pages: list[int] (page numbers, optional)
    """
    conn = get_connection()

    valid_concepts = {r[0] for r in conn.execute("SELECT id FROM concepts").fetchall()}
    valid_types = {"uses", "extends", "alternative_to", "component_of", "requires",
                   "conflicts_with", "specializes", "precedes", "enables", "complements"}

    stats = {"inserted": 0, "skipped_bad_concept": 0, "skipped_bad_type": 0, "duplicates": 0}

    for r in rels:
        fid = r["from_concept_id"]
        tid = r["to_concept_id"]
        rtype = r["relationship_type"]

        if fid not in valid_concepts:
            stats["skipped_bad_concept"] += 1
            continue
        if tid not in valid_concepts:
            stats["skipped_bad_concept"] += 1
            continue
        if rtype not in valid_types:
            stats["skipped_bad_type"] += 1
            continue

        if dry_run:
            stats["inserted"] += 1
            continue

        # Check for existing duplicate
        existing = conn.execute(
            "SELECT id FROM relationships WHERE from_concept_id = ? AND to_concept_id = ? AND relationship_type = ?",
            [fid, tid, rtype],
        ).fetchone()

        if existing:
            stats["duplicates"] += 1
            continue

        try:
            conn.execute("""
                INSERT INTO relationships
                (from_concept_id, to_concept_id, relationship_type, confidence,
                 source_type, description, provenance_sections, provenance_pages)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                fid, tid, rtype,
                r.get("confidence", 0.7),
                r.get("source_type", "explicit"),
                r.get("description", ""),
                r.get("provenance_sections", []),
                r.get("provenance_pages", []),
            ])
            stats["inserted"] += 1
        except Exception as e:
            print(f"  ERROR: {fid}->{tid} ({rtype}): {e}")

    return stats


def mark_done(label: str):
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO pipeline_metadata (key, value) VALUES (?, 'true')",
        [f"phase3_{label}"],
    )


def is_done(label: str) -> bool:
    conn = get_connection()
    result = conn.execute(
        "SELECT value FROM pipeline_metadata WHERE key = ?",
        [f"phase3_{label}"],
    ).fetchone()
    return result is not None and result[0] == "true"


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("json_file")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--label", help="Batch label for idempotency")
    args = parser.parse_args()

    if args.label and is_done(args.label):
        print(f"Batch '{args.label}' already done. Skipping.")
        return

    data = json.loads(Path(args.json_file).read_text())
    print(f"Loaded {len(data)} relationships from {args.json_file}")

    stats = insert_relationships(data, dry_run=args.dry_run)
    print(f"Results: {stats}")

    if args.label and not args.dry_run:
        mark_done(args.label)
        print(f"Marked '{args.label}' as done.")


if __name__ == "__main__":
    main()
