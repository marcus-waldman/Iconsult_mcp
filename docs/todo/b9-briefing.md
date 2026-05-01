# B9 Briefing — `generate_implementation_plan` Multi-Book Leverage

> **For a fresh session.** Read this end-to-end before doing anything. Tracks GitHub issue [#7](https://github.com/marcus-waldman/Iconsult_mcp/issues/7); scope summary is in [`post-phase-6-followups.md` § B9](post-phase-6-followups.md#b9--generate_implementation_plan-should-leverage-cross-book-canonical-clusters). This briefing turns the issue's sketch into a concrete sub-staging plan.

## TL;DR

The multi-book refactor merged on 2026-05-01 (commit `c38a993`). Phase 6's comparison memo (`docs/todo/phase-6-comparison-memo.md`) flagged the **implementation-plan stage as the largest projected post-merge multi-book payoff** — gulli's implementation-altitude content gets cited at the consultation report stage but never reaches the implementation plan, where users actually act on the recommendations. B9 closes that gap.

User goal (from the post-merge conversation): "focus more on implementation to boost rubric scores up and make effective systems." The implementation plan is the lever that turns rubric gaps into executable instructions. Today the plan stays at architectural altitude regardless of corpus depth; B9 makes it leverage gulli's hands-on chapters when they're available.

**Scope:** ~4-8 hours. Tool-layer change in `tools/implementation_plan.py` plus a live demo. **No** schema migration, **no** rubric edits, **no** new MCP tools.

## Where we are

```
main  c38a993  Merge multi-book KG refactor (Phases 1-6)
```

DB state:
- 2 books (`arsanjani_2026` 138 concepts, `gulli_2025` 180 concepts), 94 alignment-cache rows.
- 3 projects: `proj_eed395e3a026` (Phase 4e demo), `proj_e08f51f45bf7` (Phase 6 baseline, single-book), `proj_3e48fe51e735` (Phase 6 multibook).
- Live consultations from Phase 6: `7465fccc4320_20260501_053206` (baseline) and `7465fccc4320_20260501_054137` (multibook). Both have 10 pattern_assessments with provenance fields populated. **Reusable as the B9 demo input — no need to mint fresh consultations.**

29 MCP tools registered. 278/278 tests passing as of merge tip.

## What B9 changes — concrete data path

For each missing/partial pattern in the consultation, the implementation plan currently emits:

```
- [ ] **1.1** ⚙️ Watchdog Timeout
  - Status: missing → pending
  - Evidence: agent.py and prompts/* contain no timeout logic...
  - Files: `agent.py:109`, `prompts/lead_agent.txt:40`
  - Book: Ch. 7, p. 142
  - Dependencies: ...
```

The `Book: Ch. 7, p. 142` line is **always Arsanjani** today — `_get_book_ref` (lines 82-107 in `tools/implementation_plan.py`) reads chapter from `RUBRIC` (locked to Arsanjani Ch. 12 + 5-11 foundations) and page from `PATTERN_FAILURE_TEMPLATES` (locked to Arsanjani Ch. 7-12 sources). No gulli path exists.

**B9 adds**: when the assessment carries `source_book_id="gulli_2025"` AND/OR a `canonical_concept_id` whose canonical cluster has gulli members, the plan also surfaces gulli's anchor:

```
- [ ] **1.1** ⚙️ Watchdog Timeout
  - Status: missing → pending
  - Evidence: agent.py and prompts/* contain no timeout logic...
  - Files: `agent.py:109`, `prompts/lead_agent.txt:40`
  - Book: Arsanjani Ch. 7, p. 142
  - Implementation guide (gulli_2025): "Exception Handling and Recovery" §  3.2 — concrete try/except + tenacity retry pattern
  - Dependencies: ...
```

The data path:
1. `assessment.canonical_concept_id` → `canonical_concepts` row (already in schema since Phase 3a)
2. `canonical_concepts.member_concept_ids` → list of source-book concept IDs
3. For each member with `book_id="gulli_2025"`: `concepts.section_id` → `sections.chapter_id` + `sections.title` + (optionally) a deterministic 1-2 sentence excerpt
4. Splice into the plan's per-step block as a new "Implementation guide" line

All four steps use existing schema fields. No new tables, no new columns.

## Locked design decisions — do not re-litigate

| Topic | Decision |
|---|---|
| **Rubric is immutable.** | `rubric_data.py` stays untouched. Same rule as Phase 6. The rubric anchors the chapter ref; B9 adds a *secondary* citation, never overrides the primary. |
| **Schema is immutable.** | No new tables, no new columns. The data needed (canonical_concepts, source_book_id, member_concept_ids, sections.chapter_id) exists since Phase 3a-4d. |
| **No new MCP tools.** | B9 is a *behaviour change* on `generate_implementation_plan`, not a new surface. |
| **Backward compat is byte-identical for single-book consultations.** | When `consultations.project_id` is NULL OR the project triages only one book OR no assessment carries `source_book_id`/`canonical_concept_id`, the plan output stays byte-identical to today. Same invariant the Phase 4d/5a-c provenance work used. |
| **Don't migrate stored plans.** | Existing `implementation_plans` rows stay as-is. New plans get richer refs going forward. Plans are session artifacts — users regenerate when they want. |
| **Defer classifier overhaul.** | The `_classify_step_type` heuristic + 7-pattern `MECHANICAL_PATTERN_IDS` list stays for B9. If real consulting use cases show miscategorization for gulli-attributed gaps, open a separate issue. **Don't** widen scope to retune the classifier inside B9. |

## What does NOT change

- `src/iconsult_mcp/rubric_data.py` — locked.
- DB schema — no migrations.
- `tools/score_architecture.py` — locked. B9 reads its outputs but doesn't modify them.
- `tools/failure_scenarios.py` — locked. B9 reads its templates but doesn't modify them.
- The mechanical/design_decision classifier — defer to a separate issue if needed.
- Existing 278 tests — must continue to pass byte-identical.
- Phase 5a-c provenance fields' wire format — locked.

## Open questions — recommendations to ratify or override

### B9-Q1: Output shape — augment vs split

**Augment** the existing markdown plan with new per-step lines (single output, gracefully degrades on single-book) **vs split** into a parallel "implementation guide" view that emits only on multi-book.

**Recommend: augment.** Single output is simpler to consume, single tool call to invoke. Single-book consultations never see the new lines because the data path returns empty. Splitting would imply a second tool, which violates "no new MCP tools" without solving a real problem.

### B9-Q2: How much gulli content to splice — quote, cite, or summarize

**(a) Quote** an excerpt from the gulli section (long, self-contained, but plan size balloons).
**(b) Cite** chapter + section title + section ID (short, requires reader to look up).
**(c) Cite** + a deterministic 1-2 sentence summary (medium, self-contained enough to act on).

**Recommend: (c).** Mirrors the `failure_scenarios` template-summary pattern. Generation is deterministic (no LLM), fits in a single line of markdown, gives the user enough to know whether to dig in. The summary text comes from the `concepts.description` field for that gulli member (already stored from Phase 1c tagging).

### B9-Q3: Cross-book "see also" splice for arsanjani-attributed gaps

The followups doc raised B9-2: "even an arsanjani-attributed gap can benefit from 'the gulli equivalent here is X.'" Should B9 implement this in addition to provenance-aware steps?

**Recommend: yes, in the same commit.** Both use the same data path (canonical cluster → member section refs). If the cluster has gulli members and the assessment is arsanjani-attributed, render a "see also" line. If it's gulli-attributed, render the gulli line as primary. Same code, two render branches. Doesn't change scope materially.

### B9-Q4: Per-step "Why this matters" splice from failure_scenarios

The `generate_failure_scenarios` tool already produces a trigger → propagation → impact narrative for every missing pattern. The implementation plan card for that pattern has all the context to splice it in as a "Why this matters for your system" line above the current `Evidence:` line. **This overlaps with B8c (issue #6) on the rendered HTML side, but B8c is render_report; B9 is implementation_plan — different output, same data source.**

**Recommend: defer the "why this matters" splice to a B9 follow-up.** Keep B9 focused on the corpus-leverage angle (gulli citations). Splicing failure-scenario narratives is a different value add and could compete for plan-card real estate. If the user wants both, do the corpus-leverage piece first, ship, get feedback, then layer the splice in v2.

### B9-Q5: How does the plan handle a multi-member cluster with multiple gulli members?

If a canonical cluster has 2+ gulli members (rare but possible — e.g., gulli has separate chapters for "Memory Management" and "Context Management" both anchored to `shared_epistemic_memory`), the plan would emit multiple "Implementation guide" lines.

**Recommend: emit at most one per book** — the highest-confidence member, or the one whose section title is closest to the canonical cluster name. Preserves plan readability. Tie-break deterministically.

## Sub-staging proposal

| Stage | Scope | Cost | Validation |
|---|---|---|---|
| **B9a** | Read-only investigation. Walk `tools/implementation_plan.py` + write a 1-page "current behaviour" summary as a doc comment in the briefing. Confirm `_get_book_ref` is the right insertion point. Audit `assessments` field plumbing — where does `canonical_concept_id` flow from `_get_pattern_assessments` into `_build_plan_json`? | ~30 min, no code | Briefing's "data path" section confirmed against actual source code |
| **B9b** | Provenance-aware step generation (Q1=augment, Q2=cite+summary, Q3=yes both directions). New helper `_get_member_book_refs(canonical_concept_id, book_id_filter)` in `implementation_plan.py`. Updated `_get_book_ref` to also return `member_refs` list. Updated `_render_markdown` to emit "Implementation guide" / "See also" lines. New regression tests covering: single-book backcompat (byte-identical), gulli-attributed cluster (primary line), arsanjani-attributed multi-member cluster (see-also line), multi-gulli-member tie-break (Q5). | ~3-5 hours | Three new tests pass; existing 278 stay green |
| **B9c** | Live demo `scripts/verify_b9.py`. Pulls the Phase 6 6b consultation (single-book) and 6c consultation (multibook) and regenerates plans for both. Diffs the markdown side-by-side. Eyeball check: gulli-attributed steps in 6c plan show "Implementation guide (gulli_2025): ..."; 6b plan stays Arsanjani-only. Mirrors `verify_phase4e.py`/`verify_phase5c.py` shape. | ~1-2 hours | Visible diff on disk; user reviews and approves |
| **B9d** | Update CLAUDE.md `generate_implementation_plan` MCP Tools entry to mention B9 multi-book leverage. Update `MEMORY.md`'s Architecture Notes if needed. Close issue #7 with a link to the merge commit + verify_b9 output. | ~15 min | Issue closed, docs reflect new behaviour |

Total: **~4-8 hours**, single focused session.

## Files to modify

- `src/iconsult_mcp/tools/implementation_plan.py` — primary change site (`_get_book_ref`, `_build_plan_json`, `_render_markdown`)
- `tests/test_implementation_plan*.py` — extend (or add new file) with multi-book regression tests
- `scripts/verify_b9.py` — new live demo, mirrors `verify_phase4e.py`/`verify_phase5c.py`
- `CLAUDE.md` — one-line additive note on `generate_implementation_plan`
- (Optional) `MEMORY.md` — Architecture Notes refresh if a new pattern is worth surfacing

## Reuse — don't reinvent

- **`canonical_concepts` table + `member_concept_ids`** — already populated by `build_project_kg`. Just read it.
- **`sections.chapter_id` + `sections.title` + `concepts.description`** — populated by Phase 1c pipeline. Same data model already used by `ask_book` for passage retrieval.
- **`_get_pattern_assessments`** in `score_architecture.py` — already field-agnostic (returns the full step dict including `canonical_concept_id`). Confirmed in B9a investigation.
- **Phase 4b's `db.get_canonical_subgraph`** — already understands canonical clusters. Likely don't need to call it directly here, but the cluster-membership read pattern is the same.
- **`tests/test_implementation_plan*.py`** — closest prior art for fixture shape (`consultation_cleanup`, seeded `canonical_concepts`).
- **`verify_phase4e.py`** / **`verify_phase5c.py`** — reference implementations for live-demo scripts. Use the existing `proj_eed395e3a026` Phase 4e demo project if a fresh consultation is needed; otherwise reuse the Phase 6 consultation IDs above.

## Verification

```bash
# 1. Existing tests stay green
py -m pytest tests/ -q                                  # >= 278 passing

# 2. New B9 tests
py -m pytest tests/test_implementation_plan_multi_book.py -v   # if new file
# OR extension of existing test file — same idea

# 3. Live demo: same consultation, plan diff visible
py -u scripts/verify_b9.py                              # outputs side-by-side plans

# 4. Spot-check render via the Phase 6 6c consultation
py -c "
import asyncio
from iconsult_mcp.tools.implementation_plan import generate_implementation_plan
plan = asyncio.run(generate_implementation_plan(
    consultation_id='7465fccc4320_20260501_054137',
    output_dir='./tmp_b9_check',
))
print(plan['markdown_path'])
"
# Open the markdown — gulli-attributed steps should show "Implementation guide (gulli_2025)" lines
```

## Risk

Low-to-medium. The change is purely additive at the render layer; backward-compat invariants are well-established from Phase 4-5 (single-book = byte-identical). The medium risk is in the cross-book "see also" splice for arsanjani-attributed gaps (Q3) — needs a careful tie-break rule to avoid noise on consultations with many multi-member clusters. The deterministic single-line summary (Q2c) keeps the plan compact.

## Cost / time

- **B9a**: ~30 min (investigation, no code)
- **B9b**: ~3-5 hours (implementation + tests)
- **B9c**: ~1-2 hours (verify script + eyeball)
- **B9d**: ~15 min (docs + close issue)

Total: **~4-8 hours**, one session.

## Connection to user goal

> Marcus, post-merge: "I want to focus more on implementation to boost rubric scores up and make effective systems."

B9's value chain:

1. Multi-book consultation surfaces gulli-attributed gaps in the user's code.
2. Implementation plan now cites gulli's concrete implementation guidance for those gaps.
3. User executes the plan against their codebase using gulli's chapter as a reference.
4. User re-consults; rubric ratings move up; system gets more effective.

Without B9, step 2 stays at architectural altitude — gulli is acknowledged but not actionable. **B9 is the keystone that makes the multi-book corpus pay off in the user's actual implementation work.**

## After this branch

If all green:

1. Merge `fix/b9-implementation-plan-multibook` (or whatever branch name) to `main`. Single PR; preserve commits or squash per preference.
2. Close issue #7 with a link to the merge commit + the verify_b9 demo output.
3. Update `MEMORY.md` Completed Work section with a B9 entry.
4. **Open the iterative-rubric-progress-tracking opportunity** as a new issue if it's still on the radar (the B10-shaped item flagged in the post-merge conversation: cross-consultation diff that shows "supervisor_architecture went missing→implemented; Coordination rating moved emerging→established"). Independent of B9 but pairs naturally with the "boost rubric scores" feedback loop.

## First commands to run in the new session

```bash
git status                                          # confirm clean tree
git checkout -b b9-implementation-plan-multibook    # branch off main
git log --oneline -5                                # confirm c38a993 at top

# B9a investigation — read-only walk
py -m iconsult_mcp.server --check 2>&1 | tail -3    # confirm 29 tools
py -c "
from iconsult_mcp.db import get_canonical_concept, list_canonical_concepts
# Spot-check one of the gulli-attributed assessments from Phase 6 6c
print('Phase 6 6c canonical_concepts (first 3):')
for c in list_canonical_concepts(project_id='proj_3e48fe51e735')[:3]:
    print(c)
"

# Then proceed with B9b implementation per § Sub-staging.
```
