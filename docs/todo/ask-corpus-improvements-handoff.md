# Handoff Brief — Ask-Corpus RAG Pipeline Improvement Initiative

**To:** Fable (planning agent) · **From:** Marcus + Claude (Opus 4.8) · **Date:** 2026-06-10
**Status:** Brief for planning. **Do NOT implement.** Produce the two planning artifacts described in §7.

---

## 1. The ask (read this first)

The `/ask-corpus` skill (a multi-prong, context-efficient RAG pipeline over a three-book
knowledge-graph corpus) works end-to-end. We dogfooded it and it produced a literature-grounded,
adversarially-verified backlog of ~10 improvements to itself. We want to build those out
**incrementally, quick-wins first, escalating to the complex ones**, across multiple sessions.

**Your job:** read this brief (and the authoritative sources it points to in §6), then produce
the two artifacts in §7 — an **implementation plan** and a **living project-management
single-source-of-truth tracker** — designed for *cross-session* construction. Sequence the work,
make the dependencies explicit, and bake in measurement so later changes are evidence-based, not
vibes. **Plan only; do not write feature code in this pass.**

---

## 2. What `/ask-corpus` is (current state)

A Claude Code skill at `.claude/skills/ask-corpus/SKILL.md`. It answers a natural-language
question from the corpus and returns a tight, cited synthesis without dumping the bulky retrieval
into the main context. Five phases:

0. **Route** — autodetect a future server-side `ask_corpus` tool (delegate if present); else use the
   built canonical project `corpus_wide_qa` (build-first; never re-run `start_project` on the happy path).
1. **Facet decomposition** — split a compound question into 1–4 sub-questions (main thread).
2. **Parallel retrieval fan-out** — one subagent per facet, each doing `match_concepts` →
   `get_subgraph` (structural) → `ask_book` (textual), returning a compact JSON distillate only.
3. **Synthesis** — merge distillates with inline `[book_id]` provenance + cross-book agree/diverge.
4. **Adversarial verify** — a subagent tries to refute each claim against its cited passage.
5. **Deliver** — verified, cited answer + confidence/gaps footer.

**Two implementation surfaces** (a planned migration path, already wired):
- **Client-side skill** (today) — orchestrates subagents in Claude Code.
- **Future server-side MCP tool** `ask_corpus(question, project_id?, fast?)` at
  `src/iconsult_mcp/tools/ask_corpus.py` — would run the whole pipeline inside the Python process
  (synthesis/verify via the existing urllib Claude calls) and return one compact cited answer to
  ANY MCP client. **Phase 0a of the skill already autodetects it**, so when the tool lands the skill
  delegates and the client-side fan-out becomes dead fallback. Plans should state, per improvement,
  whether it belongs in the skill, the server tool, the DB/data layer, or shared.

**The corpus** (3 books, all now with populated section content + content-based embeddings):
- `arsanjani_2026` — *Agentic Architectural Patterns* (oracle/theory; Ch. 12 rubric source)
- `gulli_2025` — *Agentic Design Patterns* (implementation patterns)
- `bratanic_2025` — *Essential GraphRAG* (the GraphRAG/retrieval/eval oracle for this initiative)

---

## 3. Already done (do not re-plan)

- **§0 empty-content bug FIXED** (commit `5cda7b7`). `gulli_2025` + `arsanjani_2026` sections had
  NULL content and title-only embeddings → textual retrieval was bratanic-only. Backfilled all
  sections + re-embedded title+content; wired `populate_content` into `run_pipeline.py` phase 4 so
  it can't recur. All three books now retrieve semantically. This was item §0 of the backlog below.

---

## 4. The improvement backlog (literature-grounded, adversarially verified)

Every claim below was verified against the books by an adversarial fact-checker (10/10 upheld).
Citations are real chapters. Group/tier as you see fit — the suggested tiers in §5 are a starting
point, not a mandate.

| # | Improvement | Surface | Effort | Impact | Source |
|---|---|---|---|---|---|
| §0 | ~~Backfill section content + content embeddings~~ ✅ DONE | data | — | — | observed |
| R1 | **Query rewriting** (HyDE / step-back) before embedding the facet | skill or server | low | med | `bratanic_2025` Ch.3 |
| R2 | **Reranking** — pull a larger candidate pool, second-pass reorder with a stronger scorer | server (`ask_book`) | med | high | `bratanic_2025` Ch.3 |
| R3 | **Hybrid search** — dense + DuckDB full-text, merge results | server + FTS index | med | high | `bratanic_2025` Ch.2–3 |
| R4 | **Parent-document retrieval** — match small chunks, return full parent section | server + chunking | med-high | med | `bratanic_2025` Ch.3 |
| G1 | **Community summaries → global vs local search** over existing `canonical_concepts` clusters | server + data | med-high | high | `bratanic_2025` Ch.7 (MS GraphRAG) |
| G2 | **Richer graph queries** (text2cypher analog: parameterized subgraph filters by type/role) | server (`get_subgraph`) | low-med | low | `bratanic_2025` Ch.4 |
| O1 | **Intent-based retriever routing** — pick retrieval strategy per facet | skill | low-med | med | `bratanic_2025` Ch.5 + `arsanjani_2026` Ch.5 |
| O2 | **Answer-critic re-retrieval loop** — pre-synthesis critic re-retrieves on low confidence/gaps | skill | low-med | high | `bratanic_2025` Ch.5; `gulli_2025` Ch.4 (Reflection) |
| V1 | **Atomic-statement faithfulness** — decompose answer into atomic claims, verify each vs context | skill (verify) | low-med | high | `bratanic_2025` Ch.8 |
| E1 | **RAGAS-style metrics** — context-recall + faithfulness + answer-correctness, logged per run | new eval infra | med | high (foundational) | `bratanic_2025` Ch.8 |
| E2 | **Gold Q&A benchmark** — small designed set to regression-test retrieval changes | data/tests | med | high (foundational) | `bratanic_2025` Ch.8 |

**Cross-book framing:** `bratanic_2025` carries all the concrete technique/eval mechanics;
`arsanjani_2026`/`gulli_2025` generalize them into routing/reflection/supervisor/guardrail patterns.

---

## 5. Suggested sequencing (refine as you see fit)

- **Tier 1 — quick wins, skill-only, no infra:** R1, O1, O2, V1. Low risk, immediately usable,
  build directly on the validated pipeline. *Start here.*
- **Tier 2 — measurement foundation:** E1 + E2. Sequence early so Tiers 3–4 are testable. The
  original answer flagged "zero evaluation instrumentation" as the #1 gap.
- **Tier 3 — server-side retrieval:** R2, R3, R4 (touch `ask_book` / `search_sections_by_embedding`,
  add an FTS index). Higher leverage but cross-cutting; gate on Tier 2 metrics.
- **Tier 4 — graph/global:** G1 (best architectural fit — you already have the cluster layer), G2.
- **Cross-cutting decision:** at some tier boundary, decide whether to stand up the server-side
  `ask_corpus` MCP tool (§2) so improvements live server-side and benefit all MCP clients.

---

## 6. Authoritative sources to read before planning

- `CLAUDE.md` (repo root) — architecture, MCP tool surface, pipeline phases, DB schema, conventions.
- `.claude/skills/ask-corpus/SKILL.md` — the pipeline you're improving, in full.
- `src/iconsult_mcp/tools/ask_book.py`, `get_subgraph.py`, `match_concepts.py` — the retrieval primitives.
- `src/iconsult_mcp/db.py` — `search_sections_by_embedding` (R2/R3/R4 land here), section/canonical schema.
- `scripts/build_graph.py` (`generate_section_embeddings`), `scripts/run_pipeline.py`, `scripts/populate_content.py`.
- `scripts/align_book_pair.py`, `src/iconsult_mcp/tools/projects.py` (`build_project_kg`) — canonical layer for G1.
- Memory: `~/.claude/projects/.../memory/ask-corpus-skill.md`, `section-content-backfill-bug.md`.

---

## 7. Deliverables (what to produce in this pass)

**Artifact A — Implementation Plan** (`docs/todo/ask-corpus-improvement-plan.md` or similar):
- Phased plan, quick-wins → complex, honoring the dependency graph (esp. measurement before big bets).
- Per item: surface (skill / server / data / eval), concrete files to touch, approach sketch,
  effort estimate, **acceptance criteria**, dependencies, and the literature citation it traces to.
- Explicit decision point for whether/when to build the server-side `ask_corpus` tool.

**Artifact B — PM Single-Source-of-Truth Tracker** (`docs/todo/ask-corpus-tracker.md` or similar):
- A *living* table designed for cross-session updates: item ID, title, tier, status
  (todo/in-progress/blocked/done), owner, dependencies, acceptance criteria, links to commits/PRs, notes.
- Stable item IDs (reuse R1/R2/G1/O1/V1/E1… from §4) so sessions can reference them unambiguously.
- A short "how to use this tracker across sessions" header (where status lives, how to update it).

---

## 8. Constraints & gotchas the plan MUST respect

- **DuckDB is single-writer.** Any DB-writing script (`populate_content`, `build_graph`, re-embed,
  `build_project_kg`) requires the iconsult MCP server **stopped first** (it holds the write lock).
  Killing the Claude-Code-spawned `iconsult-mcp` servers does NOT auto-respawn them; re-enable the
  MCP integration to reconnect. Plan any data/embedding step around this.
- **Canonical layer is project-scoped & cached.** `corpus_wide_qa` is built once and reused; rebuild
  (`--rebuild` / `build_project_kg force=True`) only when books change. G1's community summaries
  should attach to the existing `canonical_concepts`, not a parallel structure.
- **Section embeddings = title + content** — keep this invariant; never embed before content exists.
- **Provenance is attribution-only** — `[book_id]` / `source_book_id` / `canonical_concept_id`
  propagate via field-agnostic readers; don't break that pattern.
- **User working agreements:** always ask before substituting a simpler approach when blocked
  (never silently downgrade); incremental over big-bang; verify changes (run the pipeline / tests),
  don't claim done without evidence. Python launcher is `py`. R lives at `C:\Program Files\R\R-4.5.1\bin`.
- **Don't regress single-book / legacy behavior** — many tools are byte-identical for non-project
  consultations by design; preserve that.

---

## 9. Definition of done for THIS handoff

Artifacts A and B exist, every backlog item (§4) appears in both with a stable ID and a literature
citation, the sequencing respects dependencies (measurement before the retrieval/graph bets), and the
tracker is usable by a fresh session with no other context. Then hand back to Marcus to green-light Tier 1.
