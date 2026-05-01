# Phase 6 Briefing — Final Merge Gate

> **For a fresh session.** Read this end-to-end before doing anything. The full plan lives at [`../multi-book-architecture-plan.md`](../multi-book-architecture-plan.md). The active-initiative memory file is `~/.claude/projects/C--Users-marcu-git-repositories-Iconsult-mcp/memory/multi_book_refactor.md`.

## TL;DR

Phases 1-5 shipped. The plumbing works: 245/245 tests green, 29 MCP tools registered, the `verify_phase4e.py` walkthrough proves cross-book canonical clusters surface in production, and the `verify_phase5c.py` rendered HTML shows provenance badges landing where they should.

Phase 6 is **not a plumbing phase**. The unit tests already prove the code is correct. **Phase 6 proves the consulting *experience* is better.** It is a side-by-side comparison of two consultations on the same codebase: one against a single-book project (arsanjani_2026 only), one against a multi-book project (arsanjani_2026 + gulli_2025). If the multi-book version surfaces evidence the single-book version misses — without diluting the Ch. 12 rubric — we merge to `main`. If not, we open a 6.5 briefing and reassess.

The success criterion is **report quality**, not test coverage. Phase 6 should produce two HTML reports next to each other and a one-page comparison memo. That memo is the merge decision document.

## Where we are

```
feat/multi-book-kg  d16ce7d  Phase 5d: docs + tracking updates for Phase 5 closure
                    c08d232  Phase 5c: stress-test badge coverage + live-render smoke script
                    b53bce2  Phase 5c: provenance badges in rendered HTML report
                    b1d7405  Phase 5b: source_book_id on every failure scenario
                    38eeb0b  Phase 5a: surface provenance in score_architecture
                    8ff27f8  docs: add Phase 5 briefing for fresh-session continuity
                    5701300  Phase 4e: end-to-end project-scoped walkthrough verified
main                a69968e
```

DB state at branch HEAD:

- 2 books: `arsanjani_2026` (oracle, mid_level, 138 concepts) and `gulli_2025` (implementation, 180 concepts), both with summaries + 1536-dim summary_embeddings.
- 94 alignment-cache rows (48 same_concept=True), all canonically ordered.
- 1 demo project from the Phase 4e walkthrough: `proj_eed395e3a026` (Phase 4e Verification) with 273 canonical_concepts. Phase 6 will not reuse this project — it'll create a fresh one matched to the chosen target codebase. Safe to leave; safe to drop.

29 MCP tools registered. Test suite: **245/245** passing.

## Locked design decisions — do not re-litigate

| Topic | Decision |
|---|---|
| **Phase 6 is a comparison phase, not a plumbing phase.** | No new code in tools/, no new tests, no schema changes. The deliverable is two reports + a memo. |
| **Apples-to-apples comparison.** | Both consultations use project-scoped routing (no legacy `project_id=None` path). The *only* variable is which books are in the project: arsanjani_2026 alone vs arsanjani_2026 + gulli_2025. This isolates the multi-book effect from the project-scoped-routing effect. |
| **Same project description, same codebase.** | Drives both consultations from identical inputs. Any difference in output comes from the corpus. |
| **Rubric is immutable.** | The Ch. 12 rubric in `rubric_data.py` does not change in Phase 6. If multi-book scoring differs from single-book scoring on the rubric ratings, that's a sign of dilution — flag it. |
| **Merge criterion is qualitative + quantitative.** | Quantitative gates listed below; subjective judgement on report readability matters too. The user (Marcus) makes the merge call after reading the memo. |

## Target codebase — open question 6-Q1

We need a target codebase to consult against. Three options ranked by suitability:

1. **`Iconsult_mcp` itself.** The agentic system we've been building. Pros: full source access, rich enough to exercise multiple rubric categories (supervisor/dispatch in `server.py`, retry/backoff in `escalation.py`, blackboard, events, validate_subagent, critique loop, etc.), the model has full context. Cons: meta — we'd be consulting on the system that produced the consultation, which can introduce confirmation bias.
2. **`openai/openai-agents-python` `customer_service` example** (already in `tests/cases.py`). Pros: well-known, reasonably small, familiar. Cons: small enough that single-book might be sufficient — multi-book advantage may be hard to demonstrate.
3. **A fresh real-world repo Marcus is currently working on.** Best signal — represents the actual use case — but requires Marcus to nominate one.

**Recommendation: option 1 (Iconsult_mcp itself)** for the first comparison. It's the richest target available without external choice, and the consultation report is a useful artifact for the project regardless. Acknowledge confirmation-bias risk in the memo. If the result is ambiguous, fall back to option 3 with Marcus picking a real repo as a tiebreaker.

## Phase 6 scope

### 1. Set up two parallel projects

Both projects use the same project description, same codebase context, same triage settings. Difference: triaged_book_ids.

```python
# Single-book baseline
start_project(
    name="iconsult_phase6_baseline",
    project_description="<chosen codebase description>",
    triaged_book_ids=["arsanjani_2026"],
)
build_project_kg(project_id=<baseline_id>)  # singleton clusters; arsanjani concepts only

# Multi-book comparison
start_project(
    name="iconsult_phase6_multibook",
    project_description="<same description verbatim>",
    triaged_book_ids=["arsanjani_2026", "gulli_2025"],
)
build_project_kg(project_id=<multibook_id>)  # cross-book canonical clusters
```

The multi-book `build_project_kg` reuses the cached alignment verdicts (94 rows already in `concept_alignment_cache`), so this is fast — no new LLM calls.

### 2. Run two consultations

Identical inputs, end-to-end 7-step flow each:

1. READ PROJECT (Marcus + agent walk through the codebase)
2. `match_concepts(<description>, project_id=<baseline_id or multibook_id>)`
3. `plan_consultation` → `supervise_consultation`
4. Scatter-gather: `get_subgraph` per seed, `log_pattern_assessment` per pattern. **Use `source_book_id` provenance honestly** — when the evidence cites gulli_2025, log it as such.
5. `ask_book` for retrieval
6. `score_architecture`, `generate_failure_scenarios`
7. `render_report` → HTML

Same project description, same code being consulted on, same Marcus-driven traversal effort. The variable is which books the corpus draws from.

### 3. Compare

Open both rendered HTML reports side by side. Compare against the quality signals below. Write a one-page memo at `docs/todo/phase-6-comparison-memo.md` capturing:

- which signals favoured multi-book
- which signals favoured single-book or were neutral
- did multi-book dilute the rubric (any unexpected score drift)
- subjective: which report would Marcus rather hand to a stakeholder
- merge / 6.5 decision

## Quality signals — quantitative gates

| Signal | Read from | Multi-book wins if |
|---|---|---|
| Cross-book canonical clusters in scorecard | Render HTML / `score_architecture` per-pattern entries | At least 1 assessed pattern in the multi-book scorecard has a `canonical_concept_id` whose canonical cluster spans both books (check `canonical_concepts.member_concept_ids` for member book diversity) |
| Passage diversity | `ask_book` response across the consultation | At least 1 passage in the multi-book consultation cites `gulli_2025`. Single-book baseline can never have this. |
| `by_source_book` rollup | `score_architecture.overall_summary["by_source_book"]` | Multi-book shows non-zero counts for both books; single-book shows 1-book or no rollup |
| Provenance badges in rendered report | HTML | Multi-book report renders `[gulli_2025]` badges; single-book does not |
| Rubric scoring stability | Compare `categories[k]["rating"]` across both | **Stability is the win condition, not differentiation.** If multi-book and single-book disagree on more than 1 of 7 category ratings, flag it: the rubric is being diluted or single-book is missing evidence the multi-book corpus surfaces |
| Suggested questions / `ask_book` follow-ups | Both responses | Multi-book suggested questions reference gulli concepts the single-book version cannot reach |

## Quality signals — qualitative

- Does the multi-book report's executive_brief read as more grounded?
- Are the failure scenarios more concrete in the multi-book version (gulli is implementation-altitude, so scenarios may have more code-level specifics)?
- Does the multi-book recommendation roadmap feel additive (covers gaps single-book missed) or noisy (adds patterns the rubric doesn't anchor)?
- Subjective: which report is more useful to a senior engineer?

## Sub-staging proposal

| Stage | Scope | Cost |
|---|---|---|
| **6a** | Set up the two parallel projects (`start_project` × 2 + `build_project_kg` × 2). Verify both projects have the right book composition; multi-book project uses the cached alignments and finishes fast. | Small, ~30 min. No LLM calls (cache hits). |
| **6b** | Run the single-book baseline consultation end-to-end. Save the rendered HTML to `~/.agent/diagrams/phase6-baseline-*.html`. Capture key metrics (assessed patterns, scorecard ratings, passage book attribution, etc.). | Medium, ~1-2 hours. The agent does most of the work; Marcus reviews and adjusts. |
| **6c** | Run the multi-book consultation end-to-end. Save HTML to `~/.agent/diagrams/phase6-multibook-*.html`. Capture the same metrics. | Medium, ~1-2 hours. Same shape as 6b. |
| **6d** | Write `docs/todo/phase-6-comparison-memo.md` — one page. Decide: merge to main, or open `phase-6.5-briefing.md` describing what's missing. If merge: rebase / squash / merge to main, delete the feature branch on remote, update the user's memory. | Small, ~1-2 hours. |

Total: **likely one focused session, possibly two** depending on consultation depth. Phase 6 has no LLM-call budget concern beyond the consultations themselves (assessments use the agent — no batched Claude/OpenAI ingestion calls).

## What does NOT change in Phase 6

| Area | Reason |
|---|---|
| `tools/` | The plumbing is done; Phase 6 exercises it, doesn't modify it. |
| `tests/` | The 245 unit tests prove correctness. Phase 6 proves usefulness, which isn't unit-testable. |
| `rubric_data.py` | Locked. Modifying the rubric in Phase 6 would invalidate the comparison (different oracles can't be compared apples-to-apples). |
| Schema | Locked. |
| `docs/multi-book-architecture-plan.md` | Update only the Implementation Tracking status preamble + add a Phase 6 row at the end of the comparison memo's commit. |
| Branch strategy | Phase 6 stays on `feat/multi-book-kg`. Merge happens at the end if 6d says yes. |

If Phase 6 reveals a real bug or missing feature (e.g., the canonical-name-in-roadmap thing that was deferred from 5c surfaces as actually-needed), open a side branch off `feat/multi-book-kg`, fix it, then resume the comparison. Don't bury bug fixes inside Phase 6 narrative.

## Reuse — don't reinvent

- **Both consultations follow the same 7-step workflow** documented in `CLAUDE.md` and the `consult` prompt. No new instructions needed.
- **`verify_phase4e.py` and `verify_phase5c.py`** demonstrate the project-scoped read path end-to-end. Phase 6 is a *human-driven* version of the same flow with deeper assessment + narrative content — the scripts are reference implementations for the orchestration.
- **The `consultation_id` is the only state needed** to thread through tools (project_id rides on the consultation row). Don't build comparison plumbing — just track two consultation_ids.
- **Markdown comparison tables** are enough for the memo. No new HTML, no diff-viewer skill, no rendered side-by-side. Two HTML reports + one markdown memo is the deliverable.

## Open questions

### 6-Q1: Which codebase to consult on?

Recommendation above: `Iconsult_mcp` itself first; fall back to a real repo Marcus picks if the result is ambiguous. **Lock this at session start before 6a.**

### 6-Q2: Are both consultations done by the agent autonomously, or by Marcus driving the agent?

Recommendation: **Marcus drives both consultations identically** — same prompts, same depth of probing, same assessment effort. Otherwise we're comparing "single-book quickly skimmed" vs "multi-book carefully explored," and the comparison is biased. Use a checklist (assessed patterns, depth of `get_subgraph` traversal, number of `ask_book` calls) to keep them parallel.

### 6-Q3: What's the merge criterion exactly?

Briefing's recommendation:

- **Merge** if: multi-book report has ≥1 cross-book canonical cluster on the scorecard, ≥1 gulli-sourced passage in the consultation, rubric ratings agree with single-book on at least 6 of 7 categories, AND Marcus's subjective read says "this is more useful."
- **Open 6.5** otherwise.

The merge call is Marcus's, not the agent's.

## Verification

Phase 6 has no test suite addition. Verification IS the comparison memo.

```bash
# After 6a:
py -c "
from iconsult_mcp.db import get_connection
con = get_connection()
print(con.execute('SELECT id, name, triaged_book_ids, unified_kg_built_at IS NOT NULL FROM projects WHERE name LIKE \"iconsult_phase6%\"').fetchall())
"

# After 6b / 6c: open the rendered HTML; confirm the score_architecture
# / failure_scenarios / render_report outputs reflect the project's
# book composition. Compare metrics.

# After 6d: read docs/todo/phase-6-comparison-memo.md end-to-end.
# It should answer the merge question in its first paragraph.
```

## Cost / time

- **6a**: small, ~30 min (no LLM calls — cache hits on alignment).
- **6b**: medium, ~1-2 hours of human-in-the-loop consultation.
- **6c**: medium, ~1-2 hours, same shape.
- **6d**: small to medium, ~1-2 hours (write memo, decide, optionally merge).

The variable is consultation depth — going deep on every category will run longer; quick spot-check consultations are faster but less informative.

## After Phase 6

If **merge**:
- Squash or rebase `feat/multi-book-kg` into `main`. (User preference: ask before squashing — Phase 6 commits are useful as separate history if Marcus wants them.)
- Delete the feature branch on origin.
- Update `~/.claude/projects/.../memory/multi_book_refactor.md` to reflect that the multi-book refactor is closed; the *initiative* is no longer "in progress."
- Update `MEMORY.md` to remove the In Progress entry, add a Completed Work entry.
- Open a new lightweight initiative for "second + third real-world books" if Marcus wants more corpus growth — that's now business-as-usual onboarding via `run_pipeline.py --book <new_id>` + `align_book_pair.py` + manually adding triaged_book_ids to projects, no architecture work needed.

If **6.5**:
- Open `docs/todo/phase-6.5-briefing.md` with a tight scope on what's missing. Don't reopen Phase 6 itself — close it as "comparison done, found these specific gaps" and move on.

## First commands to run in the new session

```bash
git status                                      # confirm clean tree
git branch --show-current                       # should be feat/multi-book-kg
git log --oneline -10                           # confirm d16ce7d at top
py -m pytest tests/ -q                          # 245 passing
py -m iconsult_mcp.server --check 2>&1 | tail -3   # confirm 29 tools

# Then lock 6-Q1 (target codebase) before running anything else.
```
