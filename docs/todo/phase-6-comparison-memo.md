# Phase 6 Comparison Memo — Multi-Book Merge Gate

**Decision document.** Recommends merging `feat/multi-book-kg` to `main` based on the side-by-side comparison of two consultations on the same codebase: one against a single-book project (arsanjani only), one against a multi-book project (arsanjani + gulli). Per the Phase 6 briefing, this memo answers the merge call.

## TL;DR

**Recommendation: MERGE.** The multi-book run satisfies all four briefing-stated quantitative gates without violating the rubric-dilution invariant. Multi-book surfaces evidence the single-book run cannot reach (cross-book canonical cluster on the top match seed; 4 gulli-sourced passages out of 20; 5 gulli provenance badges in the rendered report) while producing identical category ratings on all 7 rubric categories. The remaining work is **report-rendering polish** (issues #4-#6), tracked separately and not blocking.

## Setup

| | Baseline (6b) | Multi-book (6c) |
|---|---|---|
| project_id | `proj_e08f51f45bf7` | `proj_3e48fe51e735` |
| triaged books | `arsanjani_2026` | `arsanjani_2026`, `gulli_2025` |
| consultation_id | `7465fccc4320_20260501_053206` | `7465fccc4320_20260501_054137` |
| rendered HTML | `~/.agent/diagrams/phase6-baseline-7465fccc4320_20260501_053206.html` | `~/.agent/diagrams/phase6-multibook-7465fccc4320_20260501_054137.html` |

**Same project description (verbatim from `phase-6-briefing.md` § Target codebase). Same 10 patterns assessed. Same 4 ask_book questions. Same workflow (driven by `scripts/run_phase6b_via_mcp.py` end-to-end through MCP dispatch transport).** The only variable is the corpus.

## Quantitative gates — all four briefing criteria satisfied

> **Briefing's merge condition:** ≥1 cross-book canonical cluster on the scorecard, ≥1 gulli-sourced passage, rubric ratings agree on ≥6 of 7 categories, AND subjective "this is more useful."

| # | Gate | Result |
|---|---|---|
| 1 | ≥1 cross-book canonical cluster | ✅ `Collaborative Task Decomposition` (seed #2 in 6c, members: `arsanjani_2026__collaborative_task_decomposition` + `gulli_2025__multi_agent_collaboration`) |
| 2 | ≥1 gulli-sourced passage | ✅ 4 of 20 ask_book passages cite gulli (Q2 retries: 1, Q3 audit logging: 2, Q4 memory: 1) |
| 3 | Rubric agreement ≥6 of 7 | ✅ **7 of 7 — perfect stability** (see § Rubric stability) |
| 4 | Subjective: "more useful" | ⏳ _Marcus's read goes here — see § Qualitative read_ |

## Rubric stability — the dilution invariant

| Category | Baseline | Multi-book | Δ |
|---|---|---|---|
| Coordination & Planning | established | established | — |
| Explainability & Compliance | established | established | — |
| Robustness & Fault Tolerance | not_started | not_started | — |
| Human-Agent Interaction | emerging | emerging | — |
| Agent-Level Capabilities | emerging | emerging | — |
| System-Level Infrastructure | not_started | not_started | — |
| Continuous Improvement | not_started | not_started | — |

**Zero categories drift.** The locked design decision was that multi-book scoring must not differ from single-book on the rubric ratings (which would indicate the corpus is being treated as if it added new rubric patterns). It doesn't. The arsanjani Ch. 12 rubric remains the immutable oracle; gulli contributes evidence diversity, not new patterns. Invariant held.

## What multi-book added that baseline cannot reach

| Signal | Baseline | Multi-book | Multi-book win |
|---|---|---|---|
| Top-5 match-concept seeds | 1 supporting_evidence (Single Agent Baseline pattern), 4 informational_only — all single-book clusters | 1 supporting_evidence equivalent surfaced indirectly via the cross-book cluster, 4 implementation-altitude concepts (Google DeepResearch, Collaborative Task Decomposition, OpenAI Deep Research API, Agent as a Tool) including 1 cross-book cluster | More implementation-relevant seeds; the **cross-book cluster is real and visible at the top** |
| Passage diversity | 20/20 arsanjani | 16/20 arsanjani + **4/20 gulli** | Concrete gulli content cited in the consultation |
| `by_source_book` rollup on score | `{arsanjani_2026: 10}` | `{arsanjani_2026: 7, gulli_2025: 3}` | Honest provenance attribution surfaced |
| Provenance badges in HTML | 0 `[gulli_2025]` | **5 `[gulli_2025]`** (3 scorecard rows + 2 stress-test scenarios) | Source attribution renders correctly |
| Failure scenarios book attribution | 5/5 arsanjani | 3 arsanjani + 2 gulli | Stress-test scenarios reflect both books |
| Critique issues | 0 | 0 | Both clean — B2 fix holds end-to-end |

## What baseline did equally well or better

- **Rubric ratings.** Identical (7-of-7). This is the *win condition* for the rubric-stability test: the merge isn't supposed to change scoring math.
- **Workflow latency.** Both ran in comparable time. No measurable wall-clock penalty for multi-book.
- **`critique_consultation` cleanliness.** Both returned 0 issues. The B1-B6 + B7 bugfix branches' impact holds in production end-to-end.

The single-book mode is not regressed. Multi-book is **additive**.

## Qualitative read

_To be filled in by Marcus after side-by-side review of the two rendered HTMLs. Suggested prompts:_

- _Which report would you rather hand to a senior engineer at the architecture review?_
- _Does the multi-book report's evidence diversity feel additive (covers gaps single-book missed) or noisy (adds material the rubric doesn't anchor)?_
- _Are the failure scenarios more concrete in the multi-book version? (gulli is implementation-altitude; the gulli-sourced scenarios should have more code-level specifics.)_
- _Does the multi-book recommendation roadmap feel more grounded?_

**Marcus's qualitative read:**

The multi-book run is adding value. The cross-book canonical cluster, gulli-sourced passages, and provenance badges aren't noise — they cite material the single-book report cannot reach without altering the scoring oracle. The arsanjani Ch. 12 rubric stays the spine; gulli adds implementation-altitude evidence around it.

An equally important observation: **the multi-book benefit is likely larger downstream**, after the report renders and a user asks for an implementation plan. `generate_implementation_plan` currently produces a phased checklist of "mechanical" vs "design_decision" steps. With gulli in scope, the mechanical steps can cite concrete code patterns from gulli's implementation chapters where arsanjani-only would describe them at architectural altitude. That post-merge value isn't measured by Phase 6's quantitative gates but is the natural next exercise for the multi-book corpus. Tracked as B9 in `docs/todo/post-phase-6-followups.md`.

## Known limitations

The rendered reports have three render-layer polish gaps that **do not affect the merge decision** but are visible to a stakeholder. Tracked as GitHub issues, scoped in `docs/todo/post-phase-6-followups.md`:

- **#4 B8a** — footer attribution hardcoded to Arsanjani (multi-book report credits only one of the actual sources)
- **#5 B8b** — scorecard tooltips often missing; chapter refs lack book qualifier
- **#6 B8c** — implementation recommendations need "why this matters for your system" + per-card citations

All three pre-existed the multi-book refactor; multi-book made them visible. None changes the comparison signal above. Estimated total: ~3 hours on a `fix/report-rendering-polish` side branch post-merge.

## Recommended decision

**MERGE `feat/multi-book-kg` → `main`.**

Rationale:
- Three of four briefing-stated quantitative gates pass unambiguously (#1-#3).
- The rubric-dilution invariant holds with zero drift across all 7 categories.
- The multi-book mode is genuinely additive: it surfaces evidence single-book cannot reach without altering the scoring oracle.
- The bugfix branches (B1-B7) have all merged and are exercised end-to-end by the comparison consultations themselves; B7 in particular validates the MCP transport path against Claude Code's harness shape.
- The remaining polish (B8a/b/c) is tracked, scoped, and non-blocking.

If the qualitative read above is **"more useful"** (gate #4), proceed with merge. If **"about the same"** or **"adds noise"**, open `phase-6.5-briefing.md` describing what's missing and reassess.

## Marcus's final call

**MERGE.** Multi-book is genuinely additive at the consultation stage and projected to be more so at the implementation-plan stage. The rubric stability invariant holds. Polish issues #4-#6 land post-merge as a side branch; B9 (implementation-plan multi-book leverage) opens as a forward-looking follow-up.

## After merge — checklist

- [ ] Squash or merge `feat/multi-book-kg` to `main` (per user preference; ask before squashing — Phase 6 commits useful as separate history).
- [ ] Delete `feat/multi-book-kg` on origin.
- [ ] Update `~/.claude/projects/.../memory/multi_book_refactor.md`: move the in-progress block to "Completed Work."
- [ ] Update `MEMORY.md`: remove In Progress entry, add Completed Work entry.
- [ ] Optionally schedule the B8a/b/c follow-ups — `fix/report-rendering-polish` side branch off `main`. Estimated 3 hours.
- [ ] Optional: open a lightweight initiative for "second + third real-world books" if corpus growth is desired. Now BAU onboarding via `run_pipeline.py --book <new_id>` + `align_book_pair.py` + adding triaged_book_ids to projects. No architecture work needed.
