"""
Helper script for Phase 2 insertion.

Called by the main session to insert concept-section mappings into MotherDuck.
Reads JSON from a file, inserts into concept_sections table, updates concepts.definition.

Usage:
    py scripts/insert_phase2.py data/phase2_ch01_04.json
    py scripts/insert_phase2.py data/phase2_ch05.json --dry-run
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from iconsult_mcp.db import get_connection


def insert_mappings(mappings: list[dict], dry_run: bool = False) -> dict:
    """Insert concept-section mappings into the database.

    Each mapping should have:
        concept_id: str (must exist in concepts table)
        section_id: str (must exist in sections table)
        confidence: float (0.0-1.0)
        is_primary: bool
        definition: str (optional, updates concepts.definition if provided)
    """
    conn = get_connection()

    # Validate IDs exist
    valid_concepts = {r[0] for r in conn.execute("SELECT id FROM concepts").fetchall()}
    valid_sections = {r[0] for r in conn.execute("SELECT id FROM sections").fetchall()}

    stats = {"inserted": 0, "skipped_bad_concept": 0, "skipped_bad_section": 0, "definitions_updated": 0, "duplicates": 0}

    for m in mappings:
        cid = m["concept_id"]
        sid = m["section_id"]

        if cid not in valid_concepts:
            stats["skipped_bad_concept"] += 1
            print(f"  SKIP: concept '{cid}' not in DB")
            continue
        if sid not in valid_sections:
            stats["skipped_bad_section"] += 1
            print(f"  SKIP: section '{sid}' not in DB")
            continue

        if dry_run:
            print(f"  DRY: {cid} <-> {sid} (conf={m.get('confidence', 0.8)})")
            stats["inserted"] += 1
            continue

        try:
            conn.execute(
                "INSERT INTO concept_sections (concept_id, section_id, confidence, is_primary) VALUES (?, ?, ?, ?)",
                [cid, sid, m.get("confidence", 0.8), m.get("is_primary", False)],
            )
            stats["inserted"] += 1
        except Exception as e:
            if "Duplicate" in str(e) or "duplicate" in str(e) or "PRIMARY" in str(e):
                stats["duplicates"] += 1
            else:
                print(f"  ERROR inserting {cid}<->{sid}: {e}")

        # Update definition if provided and concept doesn't have one yet
        if m.get("definition") and not dry_run:
            existing_def = conn.execute(
                "SELECT definition FROM concepts WHERE id = ?", [cid]
            ).fetchone()
            if existing_def and not existing_def[0]:
                conn.execute(
                    "UPDATE concepts SET definition = ? WHERE id = ?",
                    [m["definition"], cid],
                )
                stats["definitions_updated"] += 1

    return stats


def mark_chapter_done(chapter_label: str):
    """Mark a chapter batch as done in pipeline_metadata."""
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO pipeline_metadata (key, value) VALUES (?, 'true')",
        [f"phase2_{chapter_label}"],
    )


def is_chapter_done(chapter_label: str) -> bool:
    """Check if a chapter batch was already processed."""
    conn = get_connection()
    result = conn.execute(
        "SELECT value FROM pipeline_metadata WHERE key = ?",
        [f"phase2_{chapter_label}"],
    ).fetchone()
    return result is not None and result[0] == "true"


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("json_file", help="JSON file with mappings")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--label", help="Chapter label for idempotency (e.g. ch01_04)")
    args = parser.parse_args()

    if args.label and is_chapter_done(args.label):
        print(f"Chapter batch '{args.label}' already done. Skipping.")
        return

    data = json.loads(Path(args.json_file).read_text())
    print(f"Loaded {len(data)} mappings from {args.json_file}")

    stats = insert_mappings(data, dry_run=args.dry_run)
    print(f"Results: {stats}")

    if args.label and not args.dry_run:
        mark_chapter_done(args.label)
        print(f"Marked '{args.label}' as done.")


if __name__ == "__main__":
    main()
