# Phase 6 Briefing — Final Merge Gate

> **For a fresh session.** Read this end-to-end before doing anything. The full plan lives at [`../multi-book-architecture-plan.md`](../multi-book-architecture-plan.md). The active-initiative memory file is `~/.claude/projects/C--Users-marcu-git-repositories-Iconsult-mcp/memory/multi_book_refactor.md`.

## TL;DR

Phases 1-5 shipped. The plumbing works: 245/245 tests green, 29 MCP tools registered, the `verify_phase4e.py` walkthrough proves cross-book canonical clusters surface in production, and the `verify_phase5c.py` rendered HTML shows provenance badges landing where they should.

Phase 6 is **not a plumbing phase**. The unit tests already prove the code is correct. **Phase 6 proves the consulting *experience* is better.** It is a side-by-side comparison of two consultations on the same codebase: one against a single-book project (arsanjani_2026 only), one against a multi-book project (arsanjani_2026 + gulli_2025). If the multi-book version surfaces evidence the single-book version misses — without diluting the Ch. 12 rubric — we merge to `main`. If not, we open a 6.5 briefing and reassess.

The success criterion is **report quality**, not test coverage. Phase 6 should produce two HTML reports next to each other and a one-page comparison memo. That memo is the merge decision document.

## Where we are

```
feat/multi-book-kg  5374864  B6: demote DuckDB ALTER SEQUENCE noise from WARNING to DEBUG
                    452dfee  B5: document score_architecture overall_summary key names
                    aec64a5  B4: defensive coercion of JSON-encoded MCP tool args
                    17adbbd  B3: validate tooltip shape at render_report entry point
                    0adb02f  B2: critique no longer false-positives on match_concepts / failure scenarios
                    3e7aab2  B1: read-time dedupe in _get_pattern_assessments (latest wins)
                    14694e1  docs(phase-6): lock 6-Q1 to research-agent + bake in description
                    7eecb77  docs: add Phase 6 briefing for fresh-session continuity
                    d16ce7d  Phase 5d: docs + tracking updates for Phase 5 closure
                    [...Phase 5a-5c, 4e above this line]
main                a69968e
```

Phase 6 was paused mid-stride at 6b on 2026-05-01: 6a setup completed (both projects exist with KG built) but the 6b script run surfaced four real plumbing bugs that would also bite the next consulting agent. Those bugs were fixed on a side branch `fix/phase-6-bugs` (commits `3e7aab2..5374864`) and merged back here. Phase 6 6b can now resume cleanly. See `phase-6-bugfix-briefing.md` for the full bugfix narrative.

DB state at branch HEAD:

- 2 books: `arsanjani_2026` (oracle, mid_level, 138 concepts) and `gulli_2025` (implementation, 180 concepts), both with summaries + 1536-dim summary_embeddings.
- 94 alignment-cache rows (48 same_concept=True), all canonically ordered.
- 3 projects: `proj_eed395e3a026` (Phase 4e demo, 273 canonical_concepts), `proj_e08f51f45bf7` (Phase 6 baseline — arsanjani only), `proj_3e48fe51e735` (Phase 6 multibook — arsanjani + gulli). Both Phase 6 projects have `unified_kg_built_at` set; 6b can pick up from either.
- 1 dirty consultation row from the failed 6b attempt: `7465fccc4320_20260501_031252` on `proj_e08f51f45bf7` with 10 pattern_assessments. Safe to leave — fresh 6b runs mint new consultation_ids; the dirty row is harmless and serves as a diagnostic checkpoint.

29 MCP tools registered. Test suite: **275/275** passing (245 pre-bugfix + 30 new regression tests in B1-B6).

Bugfix-branch capabilities now available that were not before 6b paused:
- `log_pattern_assessment` is idempotent at the read layer — a re-log overrides prior assessments on the same `(consultation_id, pattern_id)`. The fresh-consultation-per-attempt workaround used by Phase 6 driver scripts is no longer required.
- `critique_consultation` no longer false-positives on `match_concepts` (which is implicit in consultation existence) or on `generate_failure_scenarios` (which now logs a `failure_scenarios_generated` step for downstream detection).
- `render_report` validates `tooltips_current`/`tooltips_target` shape at entry — bad shape returns a clean error instead of crashing deep in `_enrich_tooltips`.
- The MCP server defensively JSON-decodes string-encoded array/integer/number/boolean args at the dispatch layer. Phase 6 6a/6b can run via MCP transport instead of the one-shot Python scripts (`setup_phase6a.py`, `run_phase6_discovery.py`, `run_phase6_consultation.py`); the scripts still work but are no longer mandatory.

## Locked design decisions — do not re-litigate

| Topic | Decision |
|---|---|
| **Phase 6 is a comparison phase, not a plumbing phase.** | No new code in tools/, no new tests, no schema changes. The deliverable is two reports + a memo. |
| **Apples-to-apples comparison.** | Both consultations use project-scoped routing (no legacy `project_id=None` path). The *only* variable is which books are in the project: arsanjani_2026 alone vs arsanjani_2026 + gulli_2025. This isolates the multi-book effect from the project-scoped-routing effect. |
| **Same project description, same codebase.** | Drives both consultations from identical inputs. Any difference in output comes from the corpus. |
| **Rubric is immutable.** | The Ch. 12 rubric in `rubric_data.py` does not change in Phase 6. If multi-book scoring differs from single-book scoring on the rubric ratings, that's a sign of dilution — flag it. |
| **Merge criterion is qualitative + quantitative.** | Quantitative gates listed below; subjective judgement on report readability matters too. The user (Marcus) makes the merge call after reading the memo. |

## Target codebase — 6-Q1 LOCKED (2026-05-01)

**Target:** the `research-agent` example from `anthropics/claude-agent-sdk-demos`.
URL: https://github.com/anthropics/claude-agent-sdk-demos/tree/main/research-agent

Why this and not the alternatives originally considered (Iconsult_mcp itself; the `openai-agents-python customer_service` example): the agent-SDK research-agent is intentionally implementation-altitude (parallel subagent invocation via the `Task` tool, file-based handoffs to `files/research_notes/` etc., SDK hooks intercepting every tool call, `parent_tool_use_id` linking calls back to the spawning subagent for attribution). That's gulli_2025's territory by construction — if multi-book provides any advantage at all, this codebase should surface it. It's also small enough to consult comprehensively in a session, and external enough to dodge the confirmation-bias risk of consulting on Iconsult_mcp itself.

**Project description (use VERBATIM as `project_description` for both consultations — apples-to-apples):**

> A multi-agent research system built on the Claude Agent SDK. A Lead Agent decomposes a research request into 2–4 subtopics and orchestrates three specialist subagent roles via the `Task` tool: Researcher subagents (WebSearch + Write) gather information in parallel and persist findings to `files/research_notes/`; a Data Analyst subagent (Glob/Read/Bash/Write) extracts metrics from those notes and generates matplotlib chart PNGs in `files/charts/`; a Report Writer subagent (Skill/Write/Glob/Read/Bash) compiles a final PDF in `files/reports/`. SDK hooks (`pre_tool_use`, `post_tool_use`) intercept every tool call to log a `transcript.txt` and structured `tool_calls.jsonl` per session, with `parent_tool_use_id` linking calls back to the spawning subagent for attribution. Slash commands (`/research`, `/competitive-analysis`, `/market-trends`, `/fact-check`, `/summarize`) route different research patterns. Built for parallel subagent execution with deterministic file-based handoffs between roles.

The description was drafted from the README. **Before locking it into 6a, the agent should clone the demos repo, walk `research-agent/` source (agent.py, prompts/, utils/, .claude/), and verify the description matches reality.** If the source reveals material content the README omits (retry logic, shared state, supervision tree, error handling), revise the description and update *both consultations' input* to keep apples-to-apples. The description above is a starting point, not a contract.

Expected rubric coverage: **strong** on Coordination & Planning (lead agent decomposition + supervisor architecture + Task delegation), Agent-Level Capabilities (function calling, structured task execution), Human-Agent Interaction (`agent_delegates_to_agent` is literally the lead→researcher pattern), Explainability (hooks + transcript logs = basic_audit_logging). Expected rubric coverage: **weak/missing** on Robustness & Fault Tolerance (no retry, no watchdog, no fallback model, no failure recovery visible in README) — this is the key gap to test the dilution invariant: if multi-book scores Robustness differently from single-book *on the rubric ratings*, that's a problem, but multi-book should surface *more* gulli-sourced evidence about robustness gaps in the failure_scenarios output.

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

### 6-Q1: Which codebase to consult on? — LOCKED

Locked 2026-05-01: **`anthropics/claude-agent-sdk-demos/research-agent`**. See the "Target codebase" section above for the project description and rationale.

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

# 6-Q1 is locked: target is anthropics/claude-agent-sdk-demos/research-agent.
# Clone the demos repo to a temp dir and walk research-agent/ source
# (agent.py, prompts/, utils/, .claude/, README) BEFORE 6a. The project
# description in the "Target codebase" section above came from the README;
# verify it matches the source. Flag any material gaps before locking the
# description into start_project — both consultations need the same input.
git clone https://github.com/anthropics/claude-agent-sdk-demos /tmp/csd-demos
ls /tmp/csd-demos/research-agent/research_agent/
```
