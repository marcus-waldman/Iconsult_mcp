"""Phase 4e — end-to-end project-scoped consultation verification.

Drives the full project-scoped read path against the live
arsanjani_2026 + gulli_2025 corpus to confirm the Phase 4 plumbing
works end-to-end:

  1. start_project           -> triaged_book_ids = [arsanjani, gulli]
  2. build_project_kg        -> uses cached alignment verdicts
  3. match_concepts(p_id)    -> returns canonical concepts
  4. get_subgraph(p_id)      -> cross-book canonical edge view
  5. ask_book(p_id)          -> passages scoped to triaged books
  6. log_pattern_assessment  -> with source_book_id + canonical_concept_id
  7. score_architecture      -> cross-book provenance does not break scoring

Re-runnable: project_id is deterministic from (name, description), so
each re-run reuses the same project row. The alignment cache is
already populated; build_project_kg is idempotent.

Usage:
  py -u scripts/verify_phase4e.py
"""

from __future__ import annotations

import asyncio
import json

from iconsult_mcp.db import (
    get_connection,
    get_consultation,
    list_canonical_concepts,
)
from iconsult_mcp.tools.ask_book import ask_book
from iconsult_mcp.tools.get_subgraph import get_subgraph
from iconsult_mcp.tools.log_pattern_assessment import log_pattern_assessment
from iconsult_mcp.tools.match_concepts import match_concepts
from iconsult_mcp.tools.projects import build_project_kg, start_project
from iconsult_mcp.tools.score_architecture import score_architecture

PROJECT_NAME = "Phase 4e Verification"
PROJECT_DESCRIPTION = (
    "Multi-agent system with reflection, tool use, MCP, supervisor patterns, "
    "and fault tolerance. Agents coordinate through delegation and sometimes "
    "use swarm/consensus for shared decisions."
)


def banner(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def show(value, indent: int = 2) -> None:
    print(json.dumps(value, indent=indent, default=str))


async def main() -> int:
    banner("STEP 1 — start_project (arsanjani_2026 + gulli_2025)")
    proj = await start_project(
        name=PROJECT_NAME,
        project_description=PROJECT_DESCRIPTION,
        triaged_book_ids=["arsanjani_2026", "gulli_2025"],
    )
    if "error" in proj:
        print("FAIL:", proj)
        return 1
    project_id = proj["project_id"]
    print(f"project_id = {project_id}")
    print(f"triaged    = {proj['project']['triaged_book_ids']}")
    print(f"kg_built   = {proj['project']['unified_kg_built_at']}")

    banner("STEP 2 — build_project_kg (cache hit, no Claude calls)")
    build = await build_project_kg(
        project_id=project_id,
        force=False,
        auto_align=False,
    )
    if "error" in build:
        print("FAIL:", build)
        return 1
    print(f"skipped       = {build.get('skipped')}")
    print(f"concepts      = {build.get('concepts_total')}")
    print(f"clusters      = {build.get('clusters_total')}")
    print(f"by_role       = {build.get('by_role')}")
    print(f"multi_member  = {build.get('multi_member_count')}")

    canonicals = list_canonical_concepts(project_id)
    print(f"canonical_concepts in DB = {len(canonicals)}")

    banner("STEP 3 — match_concepts(project_id=...) -> canonical hits")
    match = await match_concepts(
        project_description=PROJECT_DESCRIPTION,
        project_id=project_id,
        max_results=10,
    )
    if "error" in match:
        print("FAIL:", match)
        return 1
    print(f"consultation_id = {match['consultation_id']}")
    print(f"scope           = {match['scope']}")
    print(f"top matches:")
    for i, m in enumerate(match["matched_concepts"][:8], 1):
        members = m.get("member_concept_ids", [])
        member_books = sorted({mid.split("__")[0] for mid in members})
        flag = "*" if m["role"] == "supporting_evidence" else " "
        print(
            f"  {i:>2}. {flag} {m['score']:.3f}  {m['name'][:50]:<50}  "
            f"{m['role']:<20}  rubric={m['rubric_pattern_id'] or '-':<30}  "
            f"members={len(members)} books={member_books}"
        )

    consultation_id = match["consultation_id"]
    cross_book_se = next(
        (
            m for m in match["matched_concepts"]
            if m["role"] == "supporting_evidence"
            and len({mid.split("__")[0] for mid in m["member_concept_ids"]}) >= 2
        ),
        None,
    )
    fallback_se = next(
        (m for m in match["matched_concepts"] if m["role"] == "supporting_evidence"),
        None,
    )
    seed = cross_book_se or fallback_se or match["matched_concepts"][0]
    print(f"\nseed for traversal = {seed['id']} ({seed['name']})")
    print(f"  members = {seed['member_concept_ids']}")

    banner("STEP 4 — get_subgraph (canonical edge view, max-confidence collapse)")
    sg = await get_subgraph(
        concept_ids=[seed["id"]],
        consultation_id=consultation_id,  # auto-pickup project_id
        max_hops=2,
        max_edges=12,
        confidence_threshold=0.5,
    )
    if "error" in sg:
        print("FAIL:", sg)
        return 1
    print(f"scope            = {sg['scope']}")
    print(f"node_count       = {sg['node_count']}")
    print(f"edge_count       = {sg['edge_count']}")
    print(f"total_edges_found= {sg['total_edges_found']}  truncated={sg['truncated']}")

    print("\nnodes (canonical):")
    for n in sg["nodes"][:8]:
        member_books = sorted({mid.split("__")[0] for mid in n["member_concept_ids"]})
        seed_marker = "[seed]" if n.get("is_seed") else ""
        print(
            f"  d={n['depth']} {seed_marker:<6} {n['name'][:46]:<46}  "
            f"{n['role']:<20}  members={len(n['member_concept_ids'])} books={member_books}"
        )

    print("\nedges (top by confidence):")
    for e in sg["edges"][:8]:
        from_node = next((n["name"] for n in sg["nodes"] if n["id"] == e["from"]), e["from"])
        to_node = next((n["name"] for n in sg["nodes"] if n["id"] == e["to"]), e["to"])
        print(
            f"  {e['confidence']:.2f}  {from_node[:30]:<30} --{e['type']:<18}-> {to_node[:30]}"
        )

    banner("STEP 5 — ask_book (project-scoped, auto-pickup project_id)")
    ab = await ask_book(
        question="How does a supervisor architecture coordinate failures and delegation across agents?",
        concept_ids=[seed["id"]],
        consultation_id=consultation_id,
        max_passages=3,
    )
    if "error" in ab:
        print("FAIL:", ab)
        return 1
    print(f"scope           = {ab['scope']}")
    print(f"project_id      = {ab['project_id']}")
    print(f"expanded members= {ab.get('expanded_member_concept_ids')}")
    print(f"passage_count   = {ab['passage_count']}")
    print("\npassages (book_id provenance):")
    for p in ab["passages"]:
        snippet = (p.get("content") or "")[:120].replace("\n", " ")
        print(
            f"  [{p.get('book_id', '-')}] ch{p.get('chapter', '?')} pp.{p.get('pages', '-')}  "
            f"score={p.get('score', 0):.3f}  '{p['title'][:40]}'  -> {snippet}..."
        )
    if ab.get("suggested_questions"):
        print("\nsuggested_questions (from expanded members):")
        for q in ab["suggested_questions"][:3]:
            print(f"  - {q}")

    banner("STEP 6 — log_pattern_assessment with provenance (cross-book)")

    rubric_evidence_canonicals = [
        c for c in canonicals if c["role"] == "supporting_evidence"
    ]
    print(f"available rubric-anchored canonicals = {len(rubric_evidence_canonicals)}")

    pattern_targets = [
        ("supervisor_architecture", "Supervisor Architecture", "implemented", "arsanjani_2026"),
        ("agent_delegates_to_agent", "Agent Delegates To Agent", "implemented", "gulli_2025"),
        ("auto_healing_pattern", "Auto-Healing Pattern", "missing", "arsanjani_2026"),
    ]
    logged = 0
    for pid, pname, status, src_book in pattern_targets:
        canonical = next(
            (c for c in rubric_evidence_canonicals if c["rubric_pattern_id"] == pid),
            None,
        )
        canonical_id = canonical["id"] if canonical else None
        result = await log_pattern_assessment(
            consultation_id=consultation_id,
            pattern_id=pid,
            pattern_name=pname,
            status=status,
            evidence=f"Phase 4e verification: {pname} sourced from {src_book}",
            source_book_id=src_book,
            canonical_concept_id=canonical_id,
        )
        if "error" in result:
            print(f"  FAIL  {pid}: {result}")
            continue
        logged += 1
        print(
            f"  {status:<13}  {pid:<30}  src={src_book:<14}  "
            f"canonical={canonical_id or '(none)'}"
        )
    print(f"logged {logged}/{len(pattern_targets)} assessments")

    banner("STEP 7 — score_architecture (cross-book provenance must not break scoring)")
    score = await score_architecture(consultation_id=consultation_id)
    if "error" in score:
        print("FAIL:", score)
        return 1
    print("\ncategory ratings:")
    for cat_key, cat in score["categories"].items():
        levels = cat["levels"]
        def _met_count(level_key: str) -> str:
            level = levels[level_key]
            patterns = level.get("patterns", [])
            met = sum(1 for p in patterns if p.get("met"))
            return f"{met}/{len(patterns)}"
        print(
            f"  {cat['name'][:30]:<30}  rating={cat['rating']:<13}  "
            f"basic/inter/adv = "
            f"{_met_count('basic')} | {_met_count('intermediate')} | {_met_count('advanced')}"
        )
    print(f"\noverall_summary:")
    show(score.get("overall_summary"))
    print(f"\ncoverage_warnings: {len(score.get('coverage_warnings', []))} warning(s)")
    for w in score.get("coverage_warnings", [])[:3]:
        print(f"  - {w}")

    banner("STEP 8 — sanity: source_book_id provenance round-trip")
    record = get_consultation(consultation_id)
    pas = [s for s in record["steps"] if s.get("type") == "pattern_assessment"]
    print(f"pattern_assessment steps in consultation = {len(pas)}")
    for pa in pas:
        print(
            f"  pattern={pa['pattern_id']:<30}  "
            f"status={pa['status']:<13}  "
            f"source_book_id={pa.get('source_book_id', '-'):<14}  "
            f"canonical_concept_id={pa.get('canonical_concept_id', '(none)')}"
        )

    banner("DONE — Phase 4e verification successful")
    print(f"project_id      = {project_id}")
    print(f"consultation_id = {consultation_id}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
