# Phase 5 Briefing — Provenance-Aware Scoring & Reporting

> **For a fresh session.** Read this end-to-end before doing anything. The full plan lives at [`../multi-book-architecture-plan.md`](../multi-book-architecture-plan.md). The active-initiative memory file is `~/.claude/projects/C--Users-marcu-git-repositories-Iconsult-mcp/memory/multi_book_refactor.md`.

## TL;DR

Phase 4 shipped. `project_id` flows through `match_concepts` → `get_subgraph` → `ask_book` → `log_pattern_assessment`, the canonical edge view works, passages carry `book_id` provenance, and pattern assessments carry `source_book_id` / `canonical_concept_id`. The end-to-end walkthrough (`scripts/verify_phase4e.py`) confirms cross-book canonical clusters work in production: a `gulli_2025`-sourced assessment routes through the rubric and lands on the scorecard.

Phase 4d intentionally did **no behaviour change** when adding the provenance fields — they're attribution-only. **Phase 5 is the consumption pass**: take the provenance that's already in `step_data` and surface it where the user can act on it. Three consumers in scope: `score_architecture`, `failure_scenarios`, `render_report`. None require schema changes; all three already receive provenance for free via `_get_pattern_assessments`.

This phase does not change the rubric or scoring math. It changes presentation: who sourced what evidence, which book a scenario draws from, how a multi-book project's scorecard distinguishes contributions. If a future consultation reports "Coordination & Planning is emerging" and the user can't tell whether that came from arsanjani patterns or gulli patterns, Phase 5 fixes that.

## Where we are

```
feat/multi-book-kg  5701300  Phase 4e: end-to-end project-scoped walkthrough verified
                    8e837ac  Phase 4d: log_pattern_assessment provenance fields
                    a2311b2  Phase 4c: project_id on ask_book + triaged-book passage scope
                    7f19bb0  Phase 4b: project_id on get_subgraph + canonical edge view
                    055a2b6  Phase 4a: project_id on match_concepts + canonical search
                    21025db  docs: add Phase 4 briefing for fresh-session continuity
                    e3d6612  fix: three more Phase 3c alias gaps companion to FCoT
main                a69968e
```

DB state at branch HEAD (post-Phase-4e walkthrough):

- 2 books: `arsanjani_2026` (oracle, mid_level, 138 concepts, summary embedded), `gulli_2025` (implementation, 180 concepts, summary embedded)
- 94 alignment-cache rows (48 same_concept=True), all canonically ordered
- **1 demo project** persisted from the verification run: `proj_eed395e3a026` ("Phase 4e Verification") with 273 canonical_concepts (44 supporting_evidence, 229 informational_only). Deterministic project_id, so re-running `verify_phase4e.py` is idempotent. Safe to leave in DB; safe to drop before merging to main if you'd rather a clean DB.

29 MCP tools registered. Test suite: **230/230** passing.

## Locked design decisions — do not re-litigate

| Topic | Decision |
|---|---|
| Database | Local DuckDB only. Unchanged. |
| Provenance fields | `step_data` already carries `source_book_id` and `canonical_concept_id` (Phase 4d). Phase 5 reads them — no schema change. |
| Scoring math | The 7-category × 3-level rubric in `rubric_data.py` is **immutable**. Provenance does not influence scoring. `score_architecture` still keys on `pattern_id` resolved through `normalize_pattern_id`. The Phase 4d invariance test enforces this. |
| Backwards compatibility | A consultation without provenance fields (legacy / single-book) must produce identical scorecard / scenario / report output to today. Phase 5 only adds attribution to multi-book consultations. |
| Rubric oracle | Ch. 12 (arsanjani) is the immutable oracle. A pattern's rubric pattern_id resolves the same regardless of which book contributed evidence — so a `gulli_2025`-sourced assessment for `agent_delegates_to_agent` lands on the same scorecard cell as an arsanjani-sourced one. |

## Phase 5 scope — three consumers, all read-only of provenance

### 1. `score_architecture` — per-pattern attribution in the scorecard

Today's per-category structure:

```
{ "name": "Coordination & Planning",
  "rating": "emerging",
  "levels": {
    "basic": {"met": 1, "patterns": [{"pattern_id": ..., "name": ..., "met": true, ...}]},
    ...
  }
}
```

**Add:** `source_book_id` and `canonical_concept_id` on each pattern entry inside `levels[k]["patterns"]`, sourced directly from the matching `pattern_assessment` step (already keyed by canonical pattern_id via `_get_pattern_assessments`). When the pattern is unassessed, both fields are absent. No category-level aggregation; just per-pattern attribution.

**Optional secondary:** roll up "by_source_book" on the overall_summary (e.g., `{"arsanjani_2026": 5, "gulli_2025": 2, "unknown": 1}`) so a consultation can answer "how much of my evidence came from each book" at a glance.

### 2. `failure_scenarios` — book attribution in scenario narratives

Today, each scenario has a `pattern_id`, `pattern_name`, and a propagation chain. Multi-book consultations should know which book the scenario template came from (book-grounded mode) or which source-book concept anchored it (when there are multiple canonical members).

**Add:** `source_book_id` on each scenario entry, populated from the matching `pattern_assessment.source_book_id` when present, else from the pattern's source-book concept ID via `normalize_pattern_id` reverse lookup. When the scenario is purely template-based (book-grounded), default to the rubric's source book (`arsanjani_2026`).

### 3. `render_report` — provenance badges in HTML

The current report template renders pattern assessments without book attribution. Two visible additions:

- **Per-pattern badges**: small inline tag like `[gulli_2025]` next to each pattern name where `source_book_id` is set.
- **Roadmap rows**: when an assessed pattern has a `canonical_concept_id`, the roadmap step references the canonical name (e.g., "Hybrid Model") so users can drill into the cluster instead of seeing a single source-book name.

The template uses slot-based replacement (`<!-- SLOT:name -->`); add slot data from the score / scenarios output, no template restructuring.

## Sub-staging proposal (lockable at session start)

| Stage | Scope | Cost |
|---|---|---|
| **5a** | `score_architecture` per-pattern attribution. Pull `source_book_id` / `canonical_concept_id` from the matching assessment step into each `levels[k]["patterns"]` entry. Optional `overall_summary["by_source_book"]` rollup. | Small, ~1-2 hours including tests. |
| **5b** | `failure_scenarios` source-book attribution. Each scenario entry gains `source_book_id`. Update both code-grounded and book-grounded modes; book-grounded defaults to `arsanjani_2026` (the rubric oracle). | Small, ~1-2 hours including tests. |
| **5c** | `render_report` provenance badges. Add slot data + small CSS tweak for the badge styling; no template restructure. | Medium, ~2-3 hours (template work + visual review). |
| **5d** | Re-run `scripts/verify_phase4e.py` against the live corpus, eyeball the scorecard / scenarios / report for correct attribution. Update `CLAUDE.md`, plan tracking. Push. | Small, ~1 hour. |

Total: **likely one focused session** (similar shape to Phase 4).

## Files that will change

| File | Change |
|---|---|
| `src/iconsult_mcp/tools/score_architecture.py` | Surface `source_book_id` / `canonical_concept_id` per pattern entry. Optional `by_source_book` summary. |
| `src/iconsult_mcp/tools/failure_scenarios.py` | Each scenario carries `source_book_id`. |
| `src/iconsult_mcp/tools/render_report.py` | Pull provenance into the slot map. |
| `src/iconsult_mcp/templates/consultation-report-template.html` | Add badge styling + per-pattern badge slot. (May need to inspect template structure first.) |
| `tests/test_score_architecture_provenance.py` | NEW. Per-pattern attribution + by_source_book rollup. |
| `tests/test_failure_scenarios_provenance.py` | NEW. Scenario carries source_book_id. |
| `tests/test_render_report_provenance.py` | NEW. HTML output contains badge for multi-book pattern. |
| `CLAUDE.md`, `docs/multi-book-architecture-plan.md` | Update tools list + Implementation Tracking. |

No new MCP tools. No new DB tables.

## Reuse — don't reinvent

- **`_get_pattern_assessments`** in `score_architecture.py` already keys assessments by canonical pattern_id and returns the entire step dict — the provenance fields fall out for free. Don't write new readers.
- **`normalize_pattern_id`** + `_PATTERN_ID_ALIASES` already book-aware (Phase 1c stripped `{book_id}__` prefixes). Score_architecture's pattern resolution doesn't need to change.
- **`render_report`** uses slot-based template replacement. Adding a new slot is a one-line `template.replace()` call — see existing slots like `<!-- SLOT:scorecard -->` for reference.
- **The verification script** (`scripts/verify_phase4e.py`) already exercises the full provenance flow end-to-end. Re-run it to validate Phase 5 changes; no new live walkthrough needed.

## Open questions

### 5a-Q1: How aggressive should `by_source_book` rollup be?

Two options:

1. **Minimal**: just a count by book on `overall_summary` (`{"arsanjani_2026": 5, "gulli_2025": 2}`). Cheap, gives a high-level "how multi-book is this consultation" signal.
2. **Per-category**: `categories[k]["by_source_book"]` showing per-category contributions. More useful for "which book covers Robustness?" questions but more surface area to maintain.

**Recommendation: option 1 first** — keep it on `overall_summary` only. If a real consultation needs per-category, easy to add. Don't pre-build for hypothetical consumers.

### 5b-Q1: What does `source_book_id` mean for a book-grounded (template-derived) failure scenario?

When a scenario is generated purely from `PATTERN_FAILURE_TEMPLATES` (no code refs from the user's project), the scenario isn't "from" any particular book in the user's evidence — it's from the rubric's templates. Two options:

1. **Default to oracle**: set `source_book_id="arsanjani_2026"` since the rubric IS the arsanjani corpus.
2. **Leave NULL**: signals "this is a template, not user evidence."

**Recommendation: option 1** — labeling the rubric's source as `arsanjani_2026` is accurate (the rubric IS arsanjani Ch. 12) and gives the report a consistent badge for every scenario. Users who want to distinguish "evidence from project" vs "scenario from template" can use the existing `mode` field.

### 5c-Q1: Badge styling

The template's existing palette uses muted blues / greens. Book badges should be **subtle** (small, low-saturation) so they don't compete visually with the rubric ratings. Suggest a small monospace tag like `[arsanjani_2026]` in 80% opacity gray rather than a colored pill. Visual review at 5d.

## Verification

```bash
# After 5a:
py -m pytest tests/test_score_architecture_provenance.py -v

# After 5b:
py -m pytest tests/test_failure_scenarios_provenance.py -v

# After 5c:
py -m pytest tests/test_render_report_provenance.py -v
# Manually open the rendered HTML in a browser, eyeball the badges.

# After 5d (end-to-end):
py -m pytest tests/ -v             # 230 + ~10 new, all green
py -u scripts/verify_phase4e.py    # walkthrough still clean; scorecard/scenarios now show provenance
```

## Cost / time

- **5a**: small, ~1-2 hours (per-pattern attribution + tests)
- **5b**: small, ~1-2 hours (scenarios attribution + tests)
- **5c**: medium, ~2-3 hours (template work + visual review)
- **5d**: small, ~1 hour (re-run verification, docs, push)

No LLM-call costs in Phase 5. The arsanjani+gulli alignment cache is already populated; `verify_phase4e.py` runs at cache-hit speed.

Total Phase 5 implementation: **likely one focused session**.

## First commands to run in the new session

```bash
git status                                # confirm clean tree
git branch --show-current                 # should be feat/multi-book-kg
git log --oneline -10                     # confirm 5701300 at top
py -m pytest tests/ -q                    # 230 passing
py -u scripts/verify_phase4e.py | tail -40
# Expect: all 7 steps complete, "DONE" banner, scorecard / scenarios visible.
```

## After Phase 5

Phase 6 is the final merge gate:

- Run a full 7-step consultation (READ PROJECT → match → traverse → ask → assess → score → render) on a real codebase using a multi-book project.
- Compare quality against a single-book baseline consultation on the same codebase.
- If multi-book provides **demonstrably better evidence diversity** (passages from both books, cross-book canonical clusters surfacing in the report) without diluting the rubric → merge to main.
- If not → open a 6.5 briefing and reassess.

The success criterion is **report quality**, not test coverage. The 230+ unit tests show the plumbing works; Phase 6 shows the consulting *experience* is improved.
