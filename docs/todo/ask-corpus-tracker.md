# Ask-Corpus Improvement Initiative — PM Tracker (SINGLE SOURCE OF TRUTH for status)

**Initiative:** incremental build-out of the `/ask-corpus` RAG pipeline improvements.
**Design reference (read-mostly):** `docs/todo/ask-corpus-improvement-plan.md`
**Origin brief:** `docs/todo/ask-corpus-improvements-handoff.md` (commit `b72c10b`)

## How to use this tracker across sessions

- **This file is where status lives.** The plan file holds the *design* (approach, files,
  acceptance criteria in full); this file holds the *state*. If they disagree on status,
  this file wins.
- **Start of every session:** read this file. The `Status` column + `Session log` tell a
  fresh session exactly where the initiative stands with no other context.
- **End of every session (or on any item state change):** update the item's row — `Status`,
  `Links` (commit SHAs / PR #s), `Notes` (1 line: what changed, any surprise) — and append
  one line to the **Session log**. Commit the tracker change together with (or right after)
  the work it records.
- **Statuses:** `todo` · `in-progress` · `blocked(<on what>)` · `review` (awaiting Marcus) ·
  `done` · `dropped(<why>)`. One item should normally be `in-progress` at a time
  (incremental over big-bang).
- **Item IDs are stable** (from the handoff brief §4, plus `S1`/`O1b` added by the plan).
  Reference them in commit messages (e.g. `feat(ask-corpus): R3 hybrid search …`) so links
  here stay greppable.
- **Decisions D1–D6** (plan §8) are recorded in the Decisions table below when Marcus rules;
  blocked items reference the decision they wait on.
- **Eval gate (Tiers 3–4):** an item is not `done` until its E1 delta vs. baseline is
  recorded in `Eval delta`. "Tests green" alone does not close a Tier 3–4 item.

---

## Item tracker

| ID | Title | Tier/Phase | Surface | Status | Owner | Depends on | Acceptance (short — full criteria in plan) | Literature | Links | Eval delta | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| §0 | Backfill section content + content embeddings | 0 | data | done | Marcus+Claude | — | all 3 books retrieve semantically | observed | `5cda7b7` | n/a | fixed pre-initiative; populate_content wired into pipeline |
| R1 | Query rewriting (HyDE / step-back) per facet | 1 | skill | done | Claude | — | facet → distinct `retrieval_query` in subagent brief; weak-query spot-checks improve; citations stay against original claims | bratanic_2025 Ch.3 | `1de5f3b` | n/a (pre-eval) | Phase 1 derives `retrieval_query` (step-back/HyDE-lite); brief queries on it, keeps original facet for citations; A/B at tier close |
| O1 | Intent-based retriever routing v1 | 1 | skill | done | Claude | — | intent→strategy table in SKILL.md; 4-intent smoke set shows per-intent tool emphasis | bratanic_2025 Ch.5; arsanjani_2026 Ch.5 | `f30e878` | n/a (pre-eval) | `global` intent label is the hook for O1b; Phase 1 intent table + Phase 2 ROUTING block; row-structured for O1b; A/B at tier close |
| O2 | Answer-critic re-retrieval loop (Phase 3b) | 1 | skill | done | Claude | — | 1-round cap; gap-facet triggers exactly one re-retrieval; all-high-confidence adds zero cost; skipped in --fast | bratanic_2025 Ch.5; gulli_2025 Ch.4 | `1697633` | n/a (pre-eval) | new Phase 3b; in-context critique of distillates → ≤1 re-retrieval subagent (reuses Phase 2 brief, R1 rewrite + O1 intent); --fast skip; A/B at tier close |
| V1 | Atomic-statement faithfulness verify | 1 | skill | todo | — | — | per-atomic-statement verdicts; planted uncited conjunct caught; splitter definition reusable by E1 | bratanic_2025 Ch.8 | — | n/a (pre-eval) | claim-splitter shared with E1 |
| E2 | Gold Q&A benchmark set (~20–25 q) | 2 | data/tests | todo | — | — | all fields per entry; gold_sections verified in DB; Marcus signs off frozen v1 | bratanic_2025 Ch.8 | — | n/a | human-in-the-loop authoring (draft→review→freeze) |
| E1 | RAGAS-style metrics runner + logging | 2 | eval infra | todo | — | E2, V1 | runner completes full gold set (3 metrics + section-recall proxy); **baseline committed**; --compare deltas incl. cost | bratanic_2025 Ch.8 | — | establishes baseline | logs to files not DB (single-writer); D4 decides judge impl; also logs context/cost columns (subagent count, approx tokens per phase, wall time) — feeds the post-Tier-3 context-efficiency review |
| S1 | Server-side `ask_corpus` MCP tool (decision + build) | gate 2→3 | server | blocked(D1) | — | E1, E2 | tool returns cited answer; skill 0a autodetects; E1 e2e ≥ skill baseline; legacy tools untouched | brief §2; arsanjani_2026 Ch.5 | — | vs skill baseline | planner recommends build at 2→3 boundary; Marcus rules (D1) |
| R3 | Hybrid search — dense + DuckDB FTS (BM25), RRF merge | 3 | server + FTS index | todo | — | E1, E2, D1 | FTS index survives pipeline re-run; ≥2 keyword-exact wins demonstrated; context-recall ≥ baseline | bratanic_2025 Ch.2–3 | — | — | FTS index is static — rebuild wired into pipeline; server stopped for index build |
| R2 | Reranking over wider candidate pool (K≈20) | 3 | server (`ask_book`/db) | blocked(D2,D3) | — | R3, E1, E2 | pool-then-rerank, response shape unchanged; recall ≥ R3 level; determinism per D3 test-asserted | bratanic_2025 Ch.3 | — | — | scorer choice (LLM vs MMR vs both) is Marcus's call |
| R4 | Parent-document retrieval (chunk → parent section) | 3 | server + chunking | blocked(D6) | — | E1, E2, R3 | chunk tables for all 3 books; idempotent + in pipeline; recall ≥ hybrid baseline esp. needle questions; rollback switch | bratanic_2025 Ch.3 | — | — | ~3–5× embedding spend, one-time; keep section index as fallback |
| G1 | Cluster summaries → global vs local search | 4 | server + data | blocked(D5) | — | E1, E2, D1 | all corpus_wide_qa canonicals carry summary+embedding; survives force-rebuild; global mode ≥ local on global-tagged questions | bratanic_2025 Ch.7 (MS GraphRAG) | — | — | summaries attach to canonical_concepts (no parallel structure); v1 = per-cluster |
| O1b | Intent routing v2 — route to global/hybrid | 4 | skill (or S1) | todo | — | O1, G1 | global-intent gold question demonstrably routes to global mode; global-slice e2e ≥ pre-O1b | bratanic_2025 Ch.5 | — | — | tiny: extends O1's routing table |
| G2 | Parameterized subgraph filters (type/role/book) | 4 | server (`get_subgraph`) | todo | — | — | filters asserted on both legacy+canonical paths; no-param calls byte-identical | bratanic_2025 Ch.4 | — | — | low impact per brief; schedule opportunistically |

## Decisions (plan §8 — recorded when Marcus rules)

| # | Decision | Options (lean ⭐) | Verdict | Date | Notes |
|---|---|---|---|---|---|
| D1 | S1 timing | ⭐ build at Tier 2→3 boundary / defer to 3→4 / never | — | — | gates S1, placement of R-items' orchestration + G1 global mode |
| D2 | R2 scorer | LLM listwise / deterministic MMR / ⭐ both behind param | — | — | |
| D3 | `ask_book` determinism contract | ⭐ deterministic by default, LLM steps opt-in / LLM by default | — | — | |
| D4 | E1 judge implementation | ⭐ hand-rolled via `claude_messages` (zero deps) / `ragas` library (new deps) | — | — | |
| D5 | G1 granularity | ⭐ per-cluster summaries v1 / Leiden-style multi-cluster communities | — | — | (b) only if eval shows v1 global mode underperforms |
| D6 | R4 embedding spend approval | one-time ~3–5× section embedding volume | — | — | |

## Baseline & eval ledger

| Run | Date | Git SHA | Mode | Context recall | Section-recall proxy | Faithfulness | Answer correctness | Cost (subagents / ~tokens / wall) | Notes |
|---|---|---|---|---|---|---|---|---|---|
| baseline | — | — | retrieval | — | — | — | — | — | to be recorded by E1 after Tier 1 lands |

> Context-efficiency is deliberately **not** a build tier: the skill's isolation contract
> and S1 already carry the structural wins. The cost columns above are the evidence for a
> post-Tier-3 context-efficiency review (see plan §10 session map) — optimize then, with data.

## Session log (append one line per working session)

| Date | Session focus | Items touched | Outcome |
|---|---|---|---|
| 2026-06-11 | Planning (this handoff) | all | Plan + tracker created; awaiting Marcus green-light for Tier 1 (R1, O1, O2, V1) |
| 2026-06-11 | Context-efficiency decision | E1 | Decided: build first, no context-efficiency tier; E1 gains cost columns (subagents/tokens/wall time); deliberate trimming pass deferred to post-Tier-3 review with data |
