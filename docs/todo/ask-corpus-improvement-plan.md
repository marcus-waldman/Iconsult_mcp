# Ask-Corpus RAG Pipeline — Implementation Plan

**Status:** PLAN — awaiting green-light for Phase 1 (Tier 1)
**Date:** 2026-06-11 · **Planned by:** Fable (Claude) · **Source brief:** `docs/todo/ask-corpus-improvements-handoff.md` (commit `b72c10b`)
**Living tracker (single source of truth for status):** `docs/todo/ask-corpus-tracker.md`

This plan sequences the verified improvement backlog for `/ask-corpus` (the multi-prong,
context-efficient RAG pipeline over the three-book corpus) from quick wins to complex bets,
with measurement infrastructure landing *before* the big retrieval/graph changes so every
Tier 3–4 item is judged on evidence, not vibes.

---

## 0. Code-verification notes (plan inputs checked against the repo, 2026-06-11)

The handoff brief's snapshots were verified against current code. Facts the plan relies on:

| Verified fact | Where | Why it matters |
|---|---|---|
| `ask_book` is a single-pass dense search: `embed_query(question)` → `search_sections_by_embedding(max_results=max_passages)`, default 3 passages, 4 000-char/passage and 15 000-char/response caps | `tools/ask_book.py` | R2 reranking means widening the pool *inside* `ask_book`/db, then cutting back to `max_passages` — the MCP response shape never changes |
| `search_sections_by_embedding` is pure cosine over `section_embeddings`, with optional `concept_ids` (via `concept_sections` join) and `book_ids` filters AND-ed | `db.py:1740` | R2/R3/R4 all land here; the filters must survive every retrieval upgrade |
| **No FTS extension anywhere** — only VSS is installed/loaded (`db.py:56-57`) | `db.py`, whole `src/` grep | R3 is a real infra add (DuckDB `fts` extension + `PRAGMA create_fts_index`), not a query tweak |
| `claude_messages()` urllib helper exists and is already used by alignment adjudication | `embed.py:153`, `scripts/align_book_pair.py` | Server-side synthesis/verify/rerank/eval-judging has its LLM primitive ready — no new HTTP deps needed |
| Section embeddings = `title + ": " + first 2300 words of content` | `scripts/build_graph.py:113-142` (`generate_section_embeddings`) | The title+content invariant; also shows long sections are *truncated* in embedding space — the motivation for R4 chunking |
| `canonical_concepts` schema: `id, project_id, name, member_concept_ids, role, rubric_pattern_id, canonical_embedding` — **no summary column** | `db.py:366` | G1 adds summary storage attached to this table (per the brief's constraint), not a parallel structure |
| `build_project_kg` = cached alignment verdicts → union-find clusters → mean-of-members embedding → skip-if-built | `tools/projects.py:286` | G1 summary generation can hook the same build/rebuild lifecycle |
| Runtime deps are only `mcp`, `pydantic`, `duckdb` | `pyproject.toml` | E1 is LLM-judged metrics via `claude_messages`, **not** the `ragas` library; G1 grouping must be pure-python. Any new dependency requires Marcus's approval first |
| Skill Phase 0a already autodetects a server-side `ask_corpus` tool and delegates | `.claude/skills/ask-corpus/SKILL.md` | S1 (server tool) ships without any skill rewrite |
| §0 empty-content bug is fixed and pipeline-proofed (commit `5cda7b7`) | `scripts/run_pipeline.py`, memory | Not re-planned here |

---

## 1. The backlog at a glance

| ID | Title | Surface | Effort | Impact | Literature | Phase |
|---|---|---|---|---|---|---|
| §0 | Backfill section content + content embeddings | data | — | — | observed | ✅ DONE (`5cda7b7`) |
| R1 | Query rewriting (HyDE / step-back) before embedding the facet | skill | low | med | `bratanic_2025` Ch. 3 | 1 |
| O1 | Intent-based retriever routing per facet (v1) | skill | low-med | med | `bratanic_2025` Ch. 5 + `arsanjani_2026` Ch. 5 | 1 |
| O2 | Answer-critic re-retrieval loop before synthesis | skill | low-med | high | `bratanic_2025` Ch. 5; `gulli_2025` Ch. 4 (Reflection) | 1 |
| V1 | Atomic-statement faithfulness in the verify pass | skill | low-med | high | `bratanic_2025` Ch. 8 | 1 |
| E2 | Gold Q&A benchmark set | data/tests | med | high (foundational) | `bratanic_2025` Ch. 8 | 2 |
| E1 | RAGAS-style metrics runner, logged per run | eval infra | med | high (foundational) | `bratanic_2025` Ch. 8 | 2 |
| S1 | **DECISION + build:** server-side `ask_corpus` MCP tool | server | med-high | high (leverage) | brief §2; `arsanjani_2026` Ch. 5 (supervisor/orchestration) | gate before 3 |
| R3 | Hybrid search — dense + DuckDB full-text (BM25), RRF merge | server + FTS index | med | high | `bratanic_2025` Ch. 2–3 | 3 |
| R2 | Reranking — wider candidate pool, second-pass scorer | server (`ask_book`/db) | med | high | `bratanic_2025` Ch. 3 | 3 |
| R4 | Parent-document retrieval — match small chunks, return parent section | server + chunking infra | med-high | med | `bratanic_2025` Ch. 3 | 3 |
| G1 | Community/cluster summaries → global vs local search | server + data | med-high | high | `bratanic_2025` Ch. 7 (MS GraphRAG) | 4 |
| G2 | Richer graph queries — parameterized subgraph filters | server (`get_subgraph`) | low-med | low | `bratanic_2025` Ch. 4 | 4 |
| O1b | Intent routing v2 — route to hybrid/global/local strategies | skill (or S1 tool) | low | med | `bratanic_2025` Ch. 5 | 4 |

## 2. Dependency graph

```
§0 (DONE)
 ├─→ R1, O1, O2, V1          (Tier 1: skill-only, independent of each other, parallelizable)
 │
 ├─→ E2 ──→ E1               (Tier 2: gold set first, then metrics runner that consumes it)
 │           │
 │           ├─→ [S1 DECISION POINT]   (decide with baseline numbers in hand)
 │           │         │
 │           ├─→ R3 ──→ R2             (Tier 3: hybrid pool first, rerank operates on the pool)
 │           │         │
 │           ├─→ R4    │               (R4 independent of R3/R2 but eval-gated like them)
 │           │         │
 │           └─→ G1 ──→ O1b            (Tier 4: global mode exists → routing can target it)
 │                G2                   (G2 independent, anytime after S1 decision)
 │
 └─ V1 feeds E1 (the atomic-claim decomposition is reusable as the faithfulness
    metric's claim splitter — build V1 first, harvest it in E1)
```

Hard ordering rules:
1. **E2 before E1** — context-recall and answer-correctness need ground truth to judge against.
2. **E1+E2 before any of R2/R3/R4/G1** — the brief's #1 gap was "zero evaluation
   instrumentation"; every retrieval/graph bet must show a before/after delta on the gold set.
3. **S1 decision before Tier 3 starts** — so R2/R3/R4 are written once on the right surface.
4. **R3 before R2** — reranking presupposes a wider candidate pool; hybrid search is what
   widens (and diversifies) the pool. Building R2 first would mean reranking a pool that R3
   then changes under it.
5. **G1 before O1b** — can't route to a global-search mode that doesn't exist.

---

## 3. Phase 1 — Tier 1 quick wins (skill-only, no infra, no DB writes)

All four items edit only `.claude/skills/ask-corpus/SKILL.md` (plus its git history).
No server restart, no DB lock concerns, no risk to other tools. They can be built in one
session and are independent of each other. **Effort: ~1 session total.**

> Porting note: when S1 (server tool) later ships, the *logic* of these four items ports
> into the server pipeline as prompt/orchestration stages. They are deliberately
> prompt-level here, so the port is a transcription, not a redesign. This is why building
> them client-side first is not wasted work.

### R1 — Query rewriting (HyDE / step-back) · `bratanic_2025` Ch. 3

- **Surface:** skill (Phase 1→2 boundary).
- **Files:** `.claude/skills/ask-corpus/SKILL.md`.
- **Approach:** In Phase 1, after facet decomposition, the main thread rewrites each facet
  *in-context* (no extra tool calls) before handing it to the retrieval subagent:
  - **Step-back** rewrite for narrow/specific facets (generalize to the underlying concept
    so embedding match hits the right sections), and/or
  - **HyDE-lite**: a 1–2 sentence hypothetical answer in book-register prose, used as the
    `project_description`/`question` for `match_concepts`/`ask_book` instead of the raw facet.
  - Subagent brief carries BOTH the original facet (for the distillate's `facet` field and
    for citation relevance judging) and the rewritten retrieval query.
- **Acceptance criteria:**
  - SKILL.md Phase 1 emits, per facet, an explicit `retrieval_query` distinct from the facet
    when rewriting fires; the subagent brief template uses it for `match_concepts` + `ask_book`.
  - Spot-check on 3 known-weak questions (e.g. acronym-heavy or overly-specific phrasings):
    rewritten queries retrieve at least one relevant passage where the raw facet missed.
  - Verify pass (Phase 4) still cites passages against the ORIGINAL facet/claims, not the
    hypothetical text (no HyDE hallucination leaking into citations).
- **Dependencies:** none. **Effort:** low.

### O1 — Intent-based retriever routing v1 · `bratanic_2025` Ch. 5 + `arsanjani_2026` Ch. 5

- **Surface:** skill (Phase 1 + subagent brief).
- **Files:** `.claude/skills/ask-corpus/SKILL.md`.
- **Approach:** Phase 1 classifies each facet's intent and the subagent brief adapts:
  - `factual` ("what is X") → textual-heavy: `ask_book` with `max_passages=4`, subgraph at
    `max_hops=1` for context only.
  - `relational` ("how does X relate to Y") → structural-heavy: `get_subgraph` at
    `max_hops=2` first, then `ask_book` scoped to the discovered relationship's concepts.
  - `comparative` ("X vs Y") → two concept seeds, subgraph union, passages per side.
  - `overview/global` ("what does the corpus say about X broadly") → flagged but routed to
    the default both-prong path for now; **this label is the hook O1b/G1 later route to
    global search**.
  - Routing table lives as a short markdown table in SKILL.md, so v2 (O1b) only edits rows.
- **Acceptance criteria:**
  - SKILL.md contains the intent→strategy table; subagent brief is parameterized by it.
  - On a 4-question smoke set (one per intent), the emitted facet notes show the intent
    label and the subagent transcripts show the corresponding tool emphasis.
- **Dependencies:** none (O1b in Phase 4 extends it). **Effort:** low-med.

### O2 — Answer-critic re-retrieval loop · `bratanic_2025` Ch. 5; `gulli_2025` Ch. 4

- **Surface:** skill (new Phase 3b between synthesis and verify).
- **Files:** `.claude/skills/ask-corpus/SKILL.md`.
- **Approach:** After merging distillates (Phase 3), the main thread runs a cheap in-context
  critique BEFORE the adversarial verify: does any facet have `confidence: low` or a
  non-empty `gaps` field that the question actually needs answered? If yes, fire **one**
  targeted re-retrieval subagent (same brief, query = the gap restated, optionally a
  different intent route per O1) and merge its distillate. **Hard cap: 1 critic round**
  (mirrors the critique_consultation 1-iteration convention) to bound cost/latency.
  In `--fast` mode the critic is skipped (consistent with skipping verify).
- **Acceptance criteria:**
  - SKILL.md has Phase 3b with the explicit 1-round cap and `--fast` skip.
  - On a deliberately compound question where one facet returns `gaps != ''`, the transcript
    shows exactly one re-retrieval subagent firing and the final answer covering the gap or
    honestly reporting it as uncovered after the retry.
  - A question with all-high confidence fires zero extra subagents (no cost regression).
- **Dependencies:** none (composes with O1 routing if both land). **Effort:** low-med.

### V1 — Atomic-statement faithfulness · `bratanic_2025` Ch. 8

- **Surface:** skill (Phase 4 verify).
- **Files:** `.claude/skills/ask-corpus/SKILL.md`.
- **Approach:** Replace the current claim→citation pair check with: (a) main thread
  decomposes the draft answer into **atomic statements** (one fact each, no conjunctions,
  pronouns resolved); (b) the verifier subagent receives the atomic list, each with its
  citation, and verdicts each independently (`yes|partial|no`); (c) the rebuilt final answer
  keeps only `yes` statements verbatim-supported, softens `partial`, drops/flags `no`.
  The decomposition prompt is written to be **reusable as E1's faithfulness claim-splitter**
  — same definition of "atomic", documented in SKILL.md so E1 can reference it.
- **Acceptance criteria:**
  - SKILL.md Phase 4 specifies atomic decomposition rules (single fact, no conjunctions,
    resolved referents) and the per-statement verdict schema.
  - On a multi-claim answer, the verifier transcript shows ≥1 verdict *per atomic statement*
    rather than per paragraph; a planted unsupported conjunct (compound claim where one half
    is uncited) gets caught at the atomic level.
- **Dependencies:** none; **feeds E1** (shared claim-splitter definition). **Effort:** low-med.

**Phase 1 exit:** all four merged to `main`, each as its own commit referencing its ID;
tracker updated; a short manual A/B note (3–5 questions, before/after observations) added to
the tracker's notes column. Then run Phase 2 to make all later judgments quantitative.

---

## 4. Phase 2 — Tier 2 measurement foundation (E2 → E1)

The brief's #1 flagged gap. Nothing in Tiers 3–4 proceeds until this exists, because
"hybrid search made things better" must be a number, not an impression. **Effort: ~1–2 sessions.**

### E2 — Gold Q&A benchmark · `bratanic_2025` Ch. 8

- **Surface:** data/tests.
- **Files (new):** `evals/gold_qa.yaml` (or `.json`), `evals/README.md`.
- **Approach:** A designed set of **~20–25 questions** with, per question:
  - `id`, `question`, `intent` (matching O1's labels), `facet_count_expected`,
  - `gold_answer` (2–5 sentences, the reference for answer-correctness),
  - `gold_facts` (3–6 atomic statements that a correct answer must contain — the
    context-recall / correctness targets),
  - `gold_sections` (section_ids known to contain the evidence; seeded from the books'
    indexes + spot-reading) and `gold_books` (which books should contribute),
  - `tags` (single-book / cross-book / relational / global) so metric slices are possible.
  - Composition: cover all three books individually, ≥5 cross-book questions (the corpus's
    differentiator), ≥3 relational (graph-favored), ≥2 global/overview (G1's target), and
    2–3 **known-hard negatives** (questions the corpus genuinely can't answer — the pipeline
    should say so, testing the gaps/honesty path).
  - Authoring is human-in-the-loop: Claude drafts candidates from the KG + passages, Marcus
    reviews/edits before they're frozen (same pattern as `generate_book_summary --draft/--commit`).
- **Acceptance criteria:**
  - `evals/gold_qa.yaml` exists with ≥20 entries, every entry has all fields, all
    `gold_sections` verified to exist in the DB (a tiny check script or test asserts this).
  - Marcus has reviewed and signed off the frozen v1 set (noted in tracker).
- **Dependencies:** none (Tier 1 NOT required, but running E1 baselines AFTER Tier 1 lands
  gives the baseline we actually iterate from). **Effort:** med.

### E1 — RAGAS-style metrics runner · `bratanic_2025` Ch. 8

- **Surface:** new eval infra.
- **Files (new):** `scripts/run_rag_eval.py`, `src/iconsult_mcp/eval_metrics.py` (judge
  prompts + scoring), `evals/runs/` (output dir, gitignored except summaries).
- **Approach:** A runner that, for each gold question, executes the retrieval pipeline and
  computes LLM-judged metrics via the existing `claude_messages()` helper (NOT the `ragas`
  package — keeps deps at zero; if Marcus prefers the real library, that's a flagged
  decision, see Open Decisions):
  - **Context recall** — fraction of `gold_facts` attributable to the retrieved passages;
    plus a cheap deterministic proxy: fraction of `gold_sections` present in retrieved
    section_ids (no LLM needed, catches retrieval regressions instantly).
  - **Faithfulness** — fraction of the answer's atomic statements (V1's splitter definition)
    supported by retrieved context.
  - **Answer correctness** — judged overlap between answer statements and `gold_facts`.
  - Two run modes: **retrieval-only** (call `match_concepts`/`ask_book`/`get_subgraph`
    in-process — fast, cheap, the default gate for R2/R3/R4) and **end-to-end** (drive the
    full skill or S1 tool — slower, used at tier boundaries).
  - **Context/cost accounting per run** (decided 2026-06-11): alongside the quality
    metrics, log subagent count, approximate token/character volume in and out per phase,
    and wall time. Quality improvements (O2's extra round, V1's decomposition, LLM rerank)
    trade tokens for accuracy — this column is what makes that trade visible, and it is
    the evidence base for a deliberate context-efficiency pass after Tier 3 (deferred by
    design; S1 delivers the structural context win on its existing schedule).
  - Output: one JSONL per run in `evals/runs/` with config hash, git SHA, per-question
    scores, aggregate + per-tag slices; a tiny `--compare run_a run_b` mode prints deltas.
    **Logging to files, not DuckDB**, sidesteps the single-writer lock entirely (runner
    only READS the DB; reads are safe while the server runs — verify this assumption on
    first run; if the read also contends, document "server stopped" in the runner's help).
- **Acceptance criteria:**
  - `py scripts/run_rag_eval.py --mode retrieval` completes on the full gold set and writes
    a run file with all three metrics + the deterministic section-recall proxy.
  - Run files include the context/cost columns (subagent count, approx token volume per
    phase, wall time); `--compare` surfaces cost deltas next to quality deltas.
  - A **baseline run is recorded and committed** (summary, not full JSONL) — this is the
    reference all Tier 3–4 deltas compare against.
  - `--compare` prints per-metric deltas with per-tag slices.
- **Dependencies:** E2 (gold set), V1 (claim-splitter definition reused). **Effort:** med.

**Phase 2 exit:** baseline metrics committed. Now and only now, Tier 3.

---

## 5. S1 — DECISION POINT: server-side `ask_corpus` MCP tool

**When:** at the Phase 2 → Phase 3 boundary, with baseline numbers in hand.
**What's being decided:** whether R2/R3/R4 (and later G1) land behind a server-side
`ask_corpus(question, project_id?, fast?)` tool in `src/iconsult_mcp/tools/ask_corpus.py`,
or stay as primitives (`ask_book` upgrades) consumed by the client-side skill.

**Recommendation (planner's): build S1 at this boundary, before Tier 3.** Reasoning:

1. **Write-once leverage.** R2/R3/R4 modify `ask_book`/`search_sections_by_embedding`
   either way — those are shared primitives. But O2/V1-style orchestration (critic loop,
   atomic verify) currently lives only in the skill; porting it into S1 *now* means Tier 3
   improvements are immediately measurable end-to-end via E1 driving one tool call, and
   every MCP client (not just Claude Code) gets the full pipeline.
2. **Eval simplicity.** E1's end-to-end mode against a single server tool is far easier to
   drive programmatically than orchestrating the Claude Code skill from a script.
3. **The skill is already future-proofed.** Phase 0a autodetect means zero skill changes on
   landing; the client-side fan-out becomes the documented fallback.
4. **All the primitives exist.** `claude_messages()` for synthesis/verify, the canonical
   project routing, asyncio fan-out via `asyncio.gather` for parallel facet retrieval.

**Counterargument (defer S1 until after Tier 3):** R2/R3/R4 are pure-retrieval changes that
benefit `ask_book` callers regardless of surface; S1 is med-high effort that delays Tier 3's
measurable wins; the skill works today. If Marcus prefers momentum on retrieval quality
first, S1 cleanly moves to the Tier 3 → Tier 4 boundary instead — nothing in R2/R3/R4
depends on it. **Marcus decides at the gate; the tracker has an explicit S1 row to record
the verdict either way.**

If built:
- **Files:** new `src/iconsult_mcp/tools/ask_corpus.py`; `server.py` (the 4 registration
  places: import, TOOL_METADATA, TOOL_DISPATCH, list_tools — per CLAUDE.md); tests
  `tests/test_ask_corpus.py`; SKILL.md gets only a confirmation note that 0a now fires.
- **Approach sketch:** pipeline = facet decomposition (`claude_messages`) → per-facet
  retrieval (`match_concepts`/`get_subgraph`/`ask_book` called as Python functions,
  `asyncio.gather` across facets) → synthesis (`claude_messages`) → atomic verify
  (`claude_messages`, V1's splitter) → compact cited answer. `fast=True` mirrors the
  skill's `--fast` (single facet, no verify). Long-running: register with an extended
  timeout like `build_project_kg`'s 600s. Internal LLM calls are non-deterministic —
  document that this tool, unlike `match_concepts`, is NOT deterministic.
- **Acceptance criteria:** tool returns a cited answer ≤ ~700 tokens for a gold-set
  question; skill Phase 0a autodetects and delegates (manual smoke test in Claude Code);
  E1 end-to-end mode can drive it; legacy tools byte-identical (no regression to existing
  31-tool surface); E1 end-to-end scores ≥ client-side skill baseline on the gold set.
- **Effort:** med-high (~2 sessions).

---

## 6. Phase 3 — Tier 3 server-side retrieval (R3 → R2 → R4)

Each item follows the same protocol: implement → `py -m pytest tests/ -v` green →
`py scripts/run_rag_eval.py --mode retrieval` → compare to baseline → record delta in
tracker → commit. **A regression on the gold set blocks merge** (working agreement:
verify, don't claim). All three touch the DB layer; any index/schema build step requires
the MCP server stopped (single-writer).

### R3 — Hybrid search: dense + FTS (BM25) with RRF merge · `bratanic_2025` Ch. 2–3

- **Surface:** server + new FTS index.
- **Files:** `db.py` (FTS install/load + index creation in init, new
  `search_sections_hybrid` or a `mode` param on `search_sections_by_embedding`),
  `tools/ask_book.py` (call the hybrid path), `scripts/run_pipeline.py` (rebuild FTS index
  after phase 4 content population — FTS indexes in DuckDB are static, they do NOT
  auto-update on data change), `tests/test_hybrid_search.py` (new).
- **Approach sketch:**
  - `INSTALL fts; LOAD fts` alongside VSS; `PRAGMA create_fts_index('sections', 'id',
    'title', 'content', overwrite=1)` — created idempotently at init when missing, and
    rebuilt by the pipeline after content changes.
  - Hybrid query: dense top-K (K≈20) via existing cosine path + BM25 top-K via
    `fts_main_sections.match_bm25(id, ?)`; merge with **Reciprocal Rank Fusion**
    (`score = Σ 1/(60 + rank)`) — rank-based fusion avoids score-scale mismatch between
    cosine and BM25 (per bratanic Ch. 3). Cut to `max_results`. Existing `concept_ids` /
    `book_ids` filters apply to BOTH legs.
  - `ask_book` gains nothing user-visible: same response shape, passages now hybrid-ranked.
    Keep a `dense_only` escape hatch (param or config) for A/B and rollback.
- **Acceptance criteria:**
  - FTS index exists and survives a pipeline re-run (rebuild wired in, single-writer note
    in the script output).
  - Keyword-exact queries (e.g. an acronym or API name appearing verbatim in one book)
    that dense search misses are retrieved by the hybrid path — ≥2 such cases demonstrated,
    ideally drawn from E2's gold set.
  - E1 retrieval-mode: **context-recall (and section-recall proxy) ≥ baseline**, no
    faithfulness regression. Delta recorded in tracker.
  - Legacy single-book consultations unaffected (existing tests green).
- **Dependencies:** E1+E2; S1 decision (placement only, not function). **Effort:** med.

### R2 — Reranking over a wider candidate pool · `bratanic_2025` Ch. 3

- **Surface:** server (`ask_book` + db).
- **Files:** `tools/ask_book.py` (pool-then-rerank step), `db.py` (pool size pass-through),
  possibly `config.py` (POOL_SIZE, RERANKER constants), `tests/test_rerank.py` (new).
- **Approach sketch:** retrieve K≈20 candidates (hybrid after R3), rerank to `max_passages`
  with a stronger second-pass scorer. **Scorer choice is a flagged design decision** (see
  Open Decisions): (a) LLM listwise rerank via `claude_messages` — strongest, adds ~1 LLM
  call of latency/cost to every `ask_book` and makes it non-deterministic (today it's
  deterministic); (b) deterministic MMR-style rerank (relevance − redundancy on existing
  embeddings) — free, deterministic, improves *diversity* but not pointwise relevance;
  (c) both, behind a `rerank` param defaulting per-tool. Plan assumes (c): MMR default in
  deterministic contexts, LLM rerank opt-in for `ask_corpus`/skill calls. **Ask Marcus
  before implementing** — this touches the determinism contract of a published tool.
- **Acceptance criteria:**
  - Pool-then-rerank in place; response shape unchanged; `rerank` behavior documented in
    the tool's inputSchema/docstring.
  - E1 retrieval-mode: **context-recall ≥ R3's level AND answer-correctness ≥ baseline**;
    if LLM rerank enabled, faithfulness not regressed. Deltas in tracker.
  - Determinism: with rerank off/MMR, same question → same passages (test-asserted).
- **Dependencies:** R3 (pool), E1+E2, scorer decision from Marcus. **Effort:** med.

### R4 — Parent-document retrieval (chunk → parent section) · `bratanic_2025` Ch. 3

- **Surface:** server + chunking infra (schema + pipeline).
- **Files:** `db.py` (new `section_chunks` + `chunk_embeddings` tables, chunk-search +
  parent-mapping path), new `scripts/chunk_sections.py` (idempotent, per-book, wired into
  `run_pipeline.py` after content population), `tools/ask_book.py` (retrieve-by-chunk,
  return-parent with dedup), `tests/test_parent_retrieval.py` (new).
- **Approach sketch:**
  - Why: section embeddings truncate at 2 300 words and average whole-section granularity —
    a sharp fact in paragraph 30 of a long section is diluted. Chunk each section's content
    into ~300–500-word overlapping windows; embed `section_title + chunk_text` (preserving
    the title+content invariant at chunk level); search chunks; map hits to parent sections;
    dedup parents keeping best chunk score; return the SAME passage shape as today (parent
    section content, existing char caps apply).
  - This is the biggest data add (~3–5× embedding rows): run per-book, server stopped,
    re-runnable. Keep the section-level index — chunks are an additional retrieval path,
    selectable/fallback, not a replacement, until eval proves it.
- **Acceptance criteria:**
  - Chunk tables populated for all 3 books; `chunk_sections.py` idempotent and in the
    pipeline; embedding invariant documented in the script docstring.
  - E1 retrieval-mode: context-recall ≥ hybrid baseline, specifically improved on the gold
    set's "needle" questions (tag them in E2); no faithfulness regression.
  - Rollback path: a config/param switch back to section-level retrieval.
- **Dependencies:** E1+E2, R3 (so the comparison is against the current best), embedding
  spend approval (one-time ~3–5× section count). **Effort:** med-high.

---

## 7. Phase 4 — Tier 4 graph/global (G1 → O1b, G2)

### G1 — Cluster summaries → global vs local search · `bratanic_2025` Ch. 7 (MS GraphRAG)

- **Surface:** server + data.
- **Files:** `db.py` (add nullable `community_summary TEXT` + `summary_embedding FLOAT[dims]`
  columns to `canonical_concepts` via idempotent ALTER — per the brief's constraint these
  attach to the EXISTING canonical layer, no parallel structure), `tools/projects.py`
  (summary generation as an opt-in stage of `build_project_kg` or a sibling
  `scripts/generate_cluster_summaries.py` reusing its lifecycle), a global-search path
  (in S1's `ask_corpus` if built, else a `mode="global"` on `ask_book`),
  `tests/test_global_search.py` (new).
- **Approach sketch:**
  - **v1 = summary per canonical cluster** (not multi-cluster Leiden communities — see Open
    Decisions): for each `canonical_concepts` row, `claude_messages` summarizes the member
    concepts' definitions + their top linked section snippets into a 3–5 sentence
    cross-book summary; embed it; store both on the row. Generation is resumable/idempotent
    (skip rows with summaries unless `--force`), runs server-stopped, and hooks the rebuild
    model: `build_project_kg force=True` clears canonical rows, so summaries regenerate
    with the layer — document this in the script.
  - **Global search** (MS GraphRAG's map-reduce, scaled to our size): embed the question →
    top-N cluster summaries → map (relevance-filter/extract per summary) → reduce
    (synthesize across summaries) via `claude_messages`. Answers "what does the corpus say
    about X broadly" questions that passage-RAG fragments.
  - **Local search** = the existing pipeline, unchanged.
- **Acceptance criteria:**
  - All `corpus_wide_qa` canonical rows carry summaries + embeddings; regeneration after a
    forced rebuild works (tested on a small fixture project).
  - Global mode answers E2's `global`-tagged questions with **answer-correctness ≥ the
    local-mode score on those same questions** (this is the whole point — measure it).
  - Legacy/canonical read paths unaffected (existing project tests green; new columns are
    nullable and ignored by field-agnostic readers).
- **Dependencies:** E1+E2, S1 decision (placement of global mode), canonical layer (exists).
  **Effort:** med-high.

### O1b — Intent routing v2: route to global/hybrid strategies · `bratanic_2025` Ch. 5

- **Surface:** skill (or S1 tool's facet planner).
- **Files:** SKILL.md routing table (or `tools/ask_corpus.py` routing logic).
- **Approach:** extend O1's routing table: `overview/global` intent → G1 global search;
  keyword-exact intents → note that hybrid (R3) covers them automatically. One row-level
  change per strategy; this is deliberately tiny.
- **Acceptance criteria:** a global-intent gold question routes to global mode (transcript
  or tool log shows it); E1 end-to-end on global-tagged slice ≥ pre-O1b.
- **Dependencies:** O1, G1. **Effort:** low.

### G2 — Richer graph queries: parameterized subgraph filters · `bratanic_2025` Ch. 4

- **Surface:** server (`get_subgraph`).
- **Files:** `tools/get_subgraph.py`, `db.py` (`get_subgraph` + `get_canonical_subgraph`
  filter pass-through), `server.py` (inputSchema for new params — remember
  `coerce_typed_args` handles array params shipped as JSON strings), `tests/test_subgraph.py`
  (extend).
- **Approach sketch:** the text2cypher *analog* (no Cypher here — parameterized filters on
  the existing traversal): optional `relationship_types: list[str]` (e.g. only
  `requires`/`conflicts_with`), `roles: list[str]` (canonical path:
  `supporting_evidence` only), `book_ids: list[str]` (raw path: restrict edge endpoints by
  book). Filters apply during BFS edge selection, both legacy and canonical paths; omitted
  params → byte-identical current behavior.
- **Acceptance criteria:** filtered traversal returns only matching edge types/roles
  (test-asserted on both paths); no-param calls byte-identical to today (regression test);
  skill/S1 retrieval briefs may use `relationship_types` for relational intents (note in
  SKILL.md).
- **Dependencies:** none hard (anytime after S1 decision); low priority per brief (impact:
  low). **Effort:** low-med.

---

## 8. Open decisions for Marcus (flagged per working agreements — none will be decided unilaterally)

| # | Decision | Options | Planner lean | Needed by |
|---|---|---|---|---|
| D1 | S1 timing | (a) build at Tier 2→3 boundary; (b) defer to Tier 3→4; (c) never (skill stays primary) | (a) — see §5 | Phase 3 start |
| D2 | R2 scorer | (a) LLM listwise rerank; (b) deterministic MMR; (c) both behind a param | (c) | R2 implementation |
| D3 | `ask_book` determinism | keep `ask_book` deterministic (rerank/rewrite opt-in only) vs allow LLM steps by default | keep deterministic by default | R1-server/R2 |
| D4 | E1 judge | hand-rolled `claude_messages` judging (zero deps) vs adopt `ragas` library (new deps: ragas, langchain, datasets…) | hand-rolled | E1 |
| D5 | G1 granularity | (a) per-cluster summaries (v1, fits "attach to canonical_concepts" constraint); (b) multi-cluster Leiden-style communities (needs community detection + arguably a parallel structure) | (a) now, (b) only if eval shows global mode underperforms | G1 |
| D6 | R4 embedding spend | one-time chunk-embedding cost (~3–5× current section embedding volume) | proceed when R4 is greenlit | R4 |

---

## 9. Constraints honored throughout (from brief §8, restated as implementation rules)

1. **DuckDB single-writer:** every DB-writing step (FTS index build, chunking, summary
   generation, re-embeds, `build_project_kg`) documents "stop the iconsult MCP server
   first" in its script help/output; killed servers don't respawn — re-enable the MCP
   integration to reconnect. E1 logs to files, not the DB, to stay lock-free.
2. **Canonical layer rebuild model:** G1 summaries live ON `canonical_concepts` and follow
   its build/force-rebuild lifecycle; nothing introduces a second source of truth.
3. **Embedding invariant:** every new embedded text (chunks, summaries) includes its
   title/name prefix and is generated only after content exists; never embed before content.
4. **Provenance:** all new retrieval paths carry `book_id` on passages and propagate
   field-agnostically; no reader hardcodes field lists.
5. **Working agreements:** open decisions (§8) go to Marcus before implementation — never
   silently downgrade; one item per commit, incremental over big-bang; every Tier 3–4 merge
   requires a green test suite AND a recorded E1 delta (verify, don't claim).
6. **No legacy regression:** non-project/single-book paths stay byte-identical; every item
   adding params defaults them to current behavior; existing test suite is the floor.

## 10. Suggested session map (cross-session construction)

| Session | Scope | Exit artifact |
|---|---|---|
| 1 | R1 + O1 + O2 + V1 (all SKILL.md) | 4 commits, manual A/B notes in tracker |
| 2 | E2 (draft gold set → Marcus review → freeze) | `evals/gold_qa.yaml` v1 |
| 3 | E1 runner + **baseline run committed** | baseline metrics in tracker |
| — | **S1 / D-decisions checkpoint with Marcus** | D1–D4 recorded in tracker |
| 4(–5) | S1 if greenlit (else skip ahead) | `ask_corpus` tool + 0a autodetect verified |
| 5 | R3 hybrid + eval delta | delta in tracker |
| 6 | R2 rerank (per D2/D3) + eval delta | delta in tracker |
| 7 | R4 chunking + eval delta | delta in tracker |
| — | **Context-efficiency review** — read E1's cost columns across all runs to date; decide whether a trimming pass (distillate schemas, O2/V1 budgets) is warranted | verdict + any follow-up items in tracker |
| 8 | G1 summaries + global mode + eval delta | delta in tracker |
| 9 | O1b + G2 + closing eval sweep | final before/after table |

Every session starts by reading `docs/todo/ask-corpus-tracker.md` (the living status SSOT)
and ends by updating it. This plan file is the *design* reference and should only change
when a decision in §8 lands or an approach is revised — status never lives here.
