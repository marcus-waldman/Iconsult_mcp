---
name: ask-corpus
description: >-
  Multi-prong, context-efficient Q&A over the Iconsult knowledge-graph corpus
  (arsanjani_2026 + gulli_2025 + bratanic_2025). Decomposes a question into
  facets, fans out ISOLATED retrieval subagents (concept match + graph
  traversal + passage RAG across all three books via the canonical layer),
  adversarially verifies each synthesized claim against its cited passage, and
  returns a tight, cited answer — WITHOUT dumping the bulky intermediate
  retrieval into the main conversation context. Use when the user has a
  substantive question to ANSWER from the books/KG. E.g. "what does the corpus
  say about X", "how does reflection relate to evaluator-optimizer",
  "/ask-corpus <question>". Do NOT use to score/consult on a user's
  architecture against the rubric — that is the heavyweight `consult` MCP
  prompt's job.
argument-hint: "<your question>  [--project <id>] [--fast]"
---

# /ask-corpus — multi-prong context-efficient corpus Q&A

You are answering a **question** against the Iconsult corpus knowledge graph.
This is the lightweight sibling of the `consult` MCP prompt: `consult` *scores an
architecture against the Ch. 12 rubric*; this skill *answers a question from the
books*. If the user actually wants an architecture maturity assessment, stop and
point them at `consult` instead.

The corpus is three books: `arsanjani_2026` (oracle / theory),
`gulli_2025` (implementation patterns), `bratanic_2025` (Essential GraphRAG).

## The contract that makes this worth having

Two properties, both non-negotiable:

- **Multi-prong** — every question is answered from *structure* (graph
  traversal: how concepts relate) AND *text* (passage RAG: what the books
  literally say), fanned across all three books through the per-project
  canonical layer (dedup + `[book_id]` provenance), with facet decomposition
  for compound questions and an adversarial verification pass at the end.
- **Context-efficient** — the bulky intermediate retrieval (raw subgraphs, full
  passages) NEVER enters this main thread. It is absorbed inside subagents that
  return only a compact distilled result. You synthesize from those distillates.

> **CONTEXT-EFFICIENCY RULES (do not violate):**
> 1. The heavy retrieval tools — `get_subgraph` and `ask_book` — are called
>    ONLY inside subagents, never directly in this main thread.
> 2. Subagents return ONLY the compact JSON schema below. They must not paste
>    raw passage text or raw subgraph JSON back to you.
> 3. In this main thread you may call only the cheap, small-payload tools:
>    `start_project`, `build_project_kg`, and at most one `match_concepts`
>    *probe*. Everything bulky is delegated.

---

## Phase 0 — Delegation autodetect + project routing

**0a. FUTURE: server-side delegation (autodetect).**
This whole skill is a client-side stand-in for a future server-side
`ask_corpus` MCP tool (see "Future work" at the bottom). Before doing anything
else, check your available tools: **if a tool named `ask_corpus` (or
`mcp__*__ask_corpus`) exists, the server-side pipeline has shipped** — call it
once with the user's question and return its result verbatim. Skip the rest of
this skill. The phases below are the fallback for when that tool is absent.

**0b. Parse arguments.**
- The user's question is the argument text (everything after `/ask-corpus`). If
  empty, ask the user what they want to know and stop.
- `--project <id>` — use this *already-built* project for canonical routing
  (skip 0c's establish/build entirely; set `PROJECT_ID` to it).
- `--rebuild` — refresh the corpus project, then answer. **This is the action to
  run after onboarding a new book** (`run_pipeline.py --book <new>`): it re-reads
  the full book list and rebuilds the canonical layer so the new book is
  included. See 0c step R.
- `--fast` — quick mode: single facet, **legacy corpus-wide** routing (no
  canonical project, no build, all books un-deduplicated), **skip the verify
  pass**. Use this when the user wants a fast answer and accepts no dedup /
  provenance rollup. In `--fast` mode, jump straight to Phase 2 with
  `PROJECT_ID = none`.

**0c. Ensure the corpus-wide canonical project is built — WITHOUT rebuilding it
every run.** Use the fixed, knowable project id `corpus_wide_qa` (so we never
have to enumerate projects, for which there is no MCP tool).

> ⚠️ **Do NOT call `start_project` on the normal path.** `start_project` does an
> INSERT-OR-REPLACE that resets `unified_kg_built_at` to NULL, which would force
> a full rebuild on *every* question. Build-first; only call `start_project` for
> first-time setup or an explicit `--rebuild`.

Normal path (default):
1. Call `build_project_kg(project_id = "corpus_wide_qa")` directly.
   - Response `skipped: true` → already built. **This is the fast path most
     runs hit.** Set `PROJECT_ID = "corpus_wide_qa"` and go to Phase 1.
   - Response `skipped: false` (stats returned) → it was unbuilt and just built.
     Set `PROJECT_ID` and continue.
   - Response `error` containing "not found" → first-time setup; go to step S.

Step S — first-time setup (project doesn't exist yet):
   a. `list_books()` → collect ALL registered book ids (this is what keeps the
      corpus current — never hardcode the book list).
   b. `start_project(name = "Corpus-Wide Q&A", project_description =
      "Cross-book question answering over the full agentic-architecture corpus",
      project_id = "corpus_wide_qa", triaged_book_ids = <all ids from a>)`.
   c. `build_project_kg(project_id = "corpus_wide_qa")`.
      - **First-ever build is a one-time ~10-min job** (aligns every book pair —
        the deferred cross-book alignment — and clusters canonical concepts).
        Per the user's standing preference, tell them it's a one-time ~10-min
        build and ask whether to proceed now or answer in `--fast` legacy mode
        this once. Do not silently downgrade.
   d. Set `PROJECT_ID = "corpus_wide_qa"`, continue.

Step R — `--rebuild` (a book was added to the corpus): run S.a → S.b → S.c
directly (skip step 1). `start_project` in S.b resets the built flag, so S.c
rebuilds without `force=True`; the alignment step reuses cached verdicts for
existing book pairs and only adjudicates the new book's pairings, so a rebuild
is far cheaper than the first build.

---

## Phase 1 — Facet decomposition (main thread, cheap)

Decide how many retrieval prongs the question needs:

- **Atomic / single-hop question** → **1 facet** (the question itself). Most
  "what is X" / "how does X work" questions.
- **Compound / comparative / broad question** → **2–4 facets**, each a focused,
  self-contained sub-question that can be retrieved independently. Split on the
  natural seams (e.g. "compare A and B under failure" → {what A does, what B
  does, how each behaves under failure}). **Hard cap: 4 facets.**

### Intent classification (per facet)

Tag each facet with ONE intent. The intent selects the retrieval strategy the
subagent applies (the routing table below), so relational questions lead with
the graph and fact lookups lead with passages. In-context labeling — no tool
calls.

| Intent | Recognize it by | Subagent retrieval strategy |
|---|---|---|
| `factual` | "what is X", "define X", "how does X work" | Textual-heavy: `ask_book` `max_passages=4`; `get_subgraph` `max_hops=1` for light context only |
| `relational` | "how does X relate to Y", "what depends on / requires X" | Structural-first: `get_subgraph` `max_hops=2` BEFORE `ask_book`, then scope `ask_book` to the concepts the subgraph surfaced |
| `comparative` | "X vs Y", "compare X and Y", "trade-offs between X and Y" | Two seeds: union both concepts' subgraphs; pull passages for EACH side |
| `overview/global` | "what does the corpus say about X broadly", "survey/overview of X" | Default both-prong (`max_hops=2`, `max_passages=4`). **Flagged `global` — O1b/G1 will later route this to global cluster-summary search** |

A facet inherits the question's intent unless the split changed it (e.g. one side
of a comparison may itself be `factual`). When unsure, default to
`overview/global` — it runs the full both-prong path and loses nothing.

Emit a one-line note to the user: the facets you'll fan out on, each tagged with
its **intent** label. Keep it terse.

### Query rewriting (per facet, in-context — no tool calls)

Before fanning out, derive a `retrieval_query` for each facet — a rewrite tuned
for embedding match. This is pure main-thread reasoning (**no extra tool
calls**), so it stays inside the context-efficiency contract. Two moves:

- **Step-back** — for narrow, jargon- or acronym-heavy facets, generalize to the
  underlying book concept so the embedding lands on the right sections. e.g.
  "how does the AEO loop bound retries?" → `retrieval_query`: "retry and
  termination control in evaluator-optimizer agent loops".
- **HyDE-lite** — when the raw phrasing is unlike book prose, write a 1–2
  sentence *hypothetical answer* in book-register prose and use THAT as the
  `retrieval_query`. e.g. "what's reflection?" → `retrieval_query`: "Reflection
  is an agentic pattern in which an agent critiques and revises its own output,
  often via a separate evaluator step, before finalizing."

When the facet is already a clean conceptual phrase, set `retrieval_query` =
facet (no rewrite fires). Each facet now carries a pair: the **original facet**
(used for the distillate's `facet` field, citation-relevance judging, and the
final answer) and the **`retrieval_query`** (a search aid only).

> ⚠️ The `retrieval_query`'s hypothetical/generalized wording must NEVER leak
> into the answer or into citations. Every claim and every citation is judged
> against the user's ORIGINAL facet/question — the Phase 4 verify enforces this,
> keeping HyDE phrasing out of the cited output.

---

## Phase 2 — Parallel retrieval fan-out (SUBAGENTS — the isolation core)

Spawn **one subagent per facet**, all in a **single message** (multiple `Agent`
tool calls, `subagent_type: general-purpose`) so they run concurrently. Give
each subagent EXACTLY this brief, substituting the facet text, its
`retrieval_query`, its `intent`, and `PROJECT_ID` (omit the `project_id` arg
entirely in `--fast` legacy mode):

> You are a retrieval prong for one facet of a corpus question. You are given the
> ORIGINAL `facet` (what your distilled answer must address) and a
> `retrieval_query` (a search-optimized rewrite of it). Use the `retrieval_query`
> as the query string for `match_concepts` and `ask_book`, but judge every
> citation's relevance against the ORIGINAL facet — the rewrite is a search aid
> only and may contain hypothetical/generalized wording. Use the Iconsult
> MCP tools (`match_concepts`, `get_subgraph`, `ask_book` — they may be exposed
> as `mcp__<server>__<name>`; if they aren't directly callable, load them first
> with ToolSearch `select:match_concepts,get_subgraph,ask_book`). Do BOTH a
> structural and a textual retrieval, then distill.
>
> ROUTING — this facet's intent is **<INTENT>**; weight the two prongs per that
> intent's strategy (adjust `max_hops` / `max_passages` / prong order in the
> steps below accordingly):
> - `factual` → textual-heavy: `ask_book` `max_passages=4`; `get_subgraph` at
>   `max_hops=1` for light context only.
> - `relational` → structural-first: run `get_subgraph` at `max_hops=2` BEFORE
>   `ask_book`, then scope `ask_book` to the concepts the subgraph surfaced.
> - `comparative` → seed BOTH compared concepts; union their subgraphs; pull
>   passages for EACH side.
> - `overview/global` → default both-prong (`max_hops=2`, `max_passages=4`).
>
> Steps (defaults shown; override per ROUTING):
>
> 1. `match_concepts(project_description = "<RETRIEVAL_QUERY>", project_id = "<PROJECT_ID>")`
>    → take the top 3 matched concept ids and the `consultation_id`.
> 2. STRUCTURAL: `get_subgraph(concept_ids = <top 3 ids>, max_hops = 2 (per ROUTING),
>    include_descriptions = true, consultation_id = "<CID>")` → read how the
>    concepts relate (edge types, neighbors).
> 3. TEXTUAL: `ask_book(question = "<RETRIEVAL_QUERY>", concept_ids = <top 3 ids>,
>    max_passages = 4 (per ROUTING), consultation_id = "<CID>")` → read the passages; note the
>    `book_id` on each. Optionally fire ONE follow-up `ask_book` using a
>    returned `suggested_question` if it sharpens the answer.
> 4. DISTILL and return **ONLY** this JSON — do NOT paste raw passages or raw
>    subgraph JSON:
>
> ```json
> {
>   "facet": "<FACET>",
>   "answer": "<=150 words answering this facet from BOTH structure and text",
>   "key_concepts": [{"name": "...", "role": "...", "book_id": "..."}],
>   "structural_insights": ["short: how concepts relate, e.g. 'Reflection requires Evaluator-Optimizer'"],
>   "citations": [
>     {"book_id": "...", "chapter": 0, "pages": "...", "section_id": "...", "quote": "<=25-word verbatim snippet"}
>   ],
>   "cross_book": "1 line: where books agree/diverge, or 'single-book'",
>   "confidence": "high|medium|low",
>   "gaps": "what the corpus did NOT answer, or '' "
> }
> ```
>
> Every claim in `answer` must trace to a `citations` entry, and each citation
> must support the ORIGINAL facet — not the `retrieval_query`. Keep it tight.

Collect the compact JSON from each subagent. That — not the raw retrieval — is
all that enters this thread.

---

## Phase 3 — Synthesis (main thread)

Merge the facet distillates into ONE coherent answer:

- Lead with the direct answer to the user's actual question.
- Carry **`[book_id]` provenance inline** on claims (e.g. "Reflection pairs with
  an evaluator-optimizer loop `[arsanjani_2026]`, which Gulli implements as a
  critique sub-agent `[gulli_2025]`").
- Surface **cross-book agreement/divergence** explicitly — that triangulation
  across theory (arsanjani) / implementation (gulli) / graphrag (bratanic) is
  the corpus's edge over single-source RAG.
- Roll up `gaps` into one honest "what the corpus doesn't cover" note.

Hold this as a draft list of {claim → citation} pairs for verification.

---

## Phase 3b — Answer-critic re-retrieval (main thread; skip if `--fast`)

Before the adversarial verify, run ONE cheap in-context critique of the merged
distillates — **no tool calls in this thread**; you are only reading the compact
JSON the subagents already returned. Ask: does any facet that the question
actually needs have `confidence: low`, OR a non-empty `gaps` field naming
something the user asked about that the corpus might still answer?

- **No** (every needed facet is `high`/`medium` confidence with no
  question-relevant gap) → fire **zero** extra subagents and go straight to
  Phase 4. This is the common path and adds no cost.
- **Yes** → fire **exactly ONE** re-retrieval subagent, using the **same Phase 2
  brief**, with:
  - `retrieval_query` = the gap restated as a focused search query (apply the R1
    rewriting moves), and
  - `intent` = re-classified for the gap per O1's table (often `relational` or
    `factual` even when the parent facet was broader).

  Merge its distillate back into the Phase 3 synthesis (revise the draft
  claim→citation list) before continuing.

> **Hard cap: 1 critic round.** Mirrors the `critique_consultation` 1-iteration
> convention. Even if the re-retrieval still leaves the gap open, do NOT loop
> again — carry the gap honestly into the Phase 5 gaps footer. One round bounds
> cost and latency.

In `--fast` mode, skip this phase entirely (consistent with skipping the verify
pass).

---

## Phase 4 — Adversarial verify (SUBAGENT) — skip if `--fast`

Spawn ONE verifier subagent. Hand it the draft claim→citation pairs and tell it
to **try to refute each claim**:

> You are an adversarial fact-checker for a corpus answer. For each claim below,
> verify it is actually supported by its cited passage. You MAY re-fetch the
> source with `ask_book(question = "<claim restated>", project_id =
> "<PROJECT_ID>", max_passages = 3)` to check. Default to "unsupported" when the
> citation does not clearly back the claim. Return ONLY:
> ```json
> {"verdicts": [{"claim": "...", "supported": "yes|partial|no", "note": "<=20 words"}]}
> ```

Apply the verdicts: **drop or visibly flag** any `no` claim, soften any
`partial` claim. Only verified content survives into the final answer.

---

## Phase 5 — Deliver

Return to the user:

1. The verified, cited answer (prose, inline `[book_id]` provenance).
2. A one-line **confidence + gaps** footer.
3. A terse provenance line: which books contributed, and the `consultation_id`(s)
   for traceability (so they can re-open the session in a `consult` flow later).

Keep the final answer focused — you did the heavy fan-out precisely so the user
gets the distillate, not the dump.

---

## Maintenance — when a new book is onboarded

Adding a book does NOT invalidate existing work. The only refresh needed for
this skill is the one canonical project:

1. Onboard the book the usual way: `seed_books_table.py`, `run_pipeline.py
   --book <new>`, `generate_book_summary.py --book <new> --commit`. This builds
   the new book's own raw KG; existing books' KGs are untouched.
2. Run `/ask-corpus --rebuild <any question>` once (or manually re-run
   `start_project` with the full book list + `build_project_kg`). This re-reads
   the book list via `list_books`, re-clusters the canonical layer, and aligns
   only the new book's pairings (existing pairs are served from the alignment
   cache). After that, normal runs hit the fast path again.

You never rebuild existing per-book KGs, the alignment cache for existing pairs,
or the rubric.

## Future work — server-side `ask_corpus` MCP tool + autodetect

**This skill is intentionally a client-side prototype.** The roadmap is to port
this exact pipeline into a server-side MCP tool, e.g.
`ask_corpus(question, project_id?, fast?)` in
`src/iconsult_mcp/tools/ask_corpus.py`, which orchestrates match → traverse →
retrieve → synthesize → verify *inside the Python process* (synthesis/verify via
the existing urllib Claude calls used by the extraction pipeline) and returns a
single compact, cited answer. Benefits: works in **any** MCP client (not just
Claude Code), and only the final answer ever crosses the MCP boundary —
maximal context efficiency by construction.

When that tool ships, **Phase 0a already autodetects it**: this skill will
detect the `ask_corpus` tool, delegate to it in one call, and the entire
client-side fan-out below becomes dead fallback code. No skill rewrite needed —
just the tool landing. Track as a follow-up issue alongside the post-Phase-6
items.
