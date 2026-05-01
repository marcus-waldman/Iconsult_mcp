# Phase 3 Briefing — Per-Project Canonical Layer

> **For a fresh session.** Read this end-to-end before doing anything. The full plan lives at [`../multi-book-architecture-plan.md`](../multi-book-architecture-plan.md). The active-initiative memory file is `~/.claude/projects/C--Users-marcu-git-repositories-Iconsult-mcp/memory/multi_book_refactor.md`.

## TL;DR

Phases 1 and 2 are in. The system has per-book KGs and a `triage_books` tool that ranks the corpus against a project description. Phase 3 builds the **per-project canonical layer**: deduplicate concepts across triaged books, classify each cluster as supporting-evidence or informational-only, and cache the result. Without Phase 3 there's no project_id to scope subsequent consultations to, and Phases 4–6 cannot proceed.

The honest constraint: full verification of alignment requires a real second book, which doesn't land until Phase 6. Phase 3 still ships — but with synthetic test fixtures plus a single-book degenerate path. The user should answer the **Open Question** at the bottom of this briefing before 3a starts.

## Where we are

```
feat/multi-book-kg  <2c-commit>  Phase 2c: closure — conftest fix + plan/briefing updates
                    7e860f5      Phase 2b: triage_books MCP tool + tests
                    fd732e8      Phase 2a: book summary draft+commit script; arsanjani_2026 summary embedded
                    9f01bb5      docs: mark Phase 1 complete + add Phase 2 briefing
                    1dd78d6      Phase 1d: end-to-end pipeline + tests pass; CLAUDE.md updated
                    d63c5c6      Phase 1c
                    b141d98      Phase 1b
                    adf8e45      Phase 1a
main                a69968e
```

Both branches are pushed to `origin`. Local DuckDB at `data/iconsult.duckdb` contains:
- 1 book (`arsanjani_2026`) with summary + 1536-dim summary_embedding
- 138 concepts / 786 sections / 583 relationships / 138+786 entity embeddings — all `book_id='arsanjani_2026'`

26 MCP tools registered. Test suite: 142/142 passing.

## Locked design decisions — do not re-litigate

| Topic | Decision |
|---|---|
| Database | Local DuckDB only (`data/iconsult.duckdb`, override via `ICONSULT_DB`). MotherDuck deferred indefinitely. |
| Triage signal | Book-summary embeddings (Phase 2 — done). |
| Unified KG cadence | **Cached per-project** (not per-consultation, not corpus-wide). Build on first consultation in a project, reuse across follow-ups. |
| Concept role | Both `supporting_evidence` and `informational_only`, tagged distinctly. Supporting-evidence concepts contribute to scoring via rubric pattern aliases (Phase 5 wires this through). |
| Concept ID convention | `{book_id}__{slug}` prefix on every concept and section ID. `normalize_pattern_id()` strips the prefix before alias lookup. Unchanged. |
| Oracle | Ch. 12 of Arsanjani is the immutable scoring oracle. Multi-book scoring works via `_PATTERN_ID_ALIASES` populated at alignment time (Phase 5 finishes the wiring; Phase 3 prepares the alias mapping data). |
| Branch strategy | Single `feat/multi-book-kg`, phase-per-commit. Merge to `main` only after all 6 phases land + a real second book is verified. |
| Phase 3 / book-2 ordering | **Hybrid execution.** Implement 3a (schema) and 3b (`start_project` + `list_books`) with the single-book corpus, then **inline a real second-book ingestion** (run the existing pipeline on a mid-level pattern book — Hohpe / Nygard / Fowler), then resume with 3c (alignment) and 3d (verification). Rationale: alignment is the LLM-judgment-heavy step where synthetic fixtures are most likely to mislead; doing it against real data avoids the synthetic-fixture trap. Note: this only inlines the *ingestion* part of Phase 6. The "run a real consultation, compare to single-book baseline" portion of Phase 6 stays at the final merge gate after Phases 4 and 5. |

## Phase 3 scope

Per the plan: "**Per-project canonical layer.** `start_project` + `build_project_kg` produce canonical concepts for a 2-book project. Alignment cache populated. Manual review of a sample of canonical clusters confirms quality."

### What's needed concretely

**New tables** (additions to `db.py`):

1. **`projects`** — per-project cache
   - `id` TEXT PK (hash of name + description, or user-supplied)
   - `name` TEXT
   - `description` TEXT (original project description used for triage)
   - `triaged_book_ids` TEXT[] (books selected by triage)
   - `unified_kg_built_at` TIMESTAMP (NULL = not yet built)
   - `created_at` TIMESTAMP

2. **`canonical_concepts`** — project-scoped alignment layer
   - `id` TEXT PK (`{project_id}__{slug}`)
   - `project_id` TEXT FK
   - `name` TEXT (canonical name; usually from oracle book if present)
   - `member_concept_ids` TEXT[] (source concepts from various books)
   - `role` TEXT (`supporting_evidence` | `informational_only`)
   - `rubric_pattern_id` TEXT (canonical Ch. 12 pattern ID; NULL if informational)
   - `canonical_embedding` FLOAT[1536] (mean of member embeddings; for project-scoped match_concepts in Phase 4)

3. **`concept_alignment_cache`** — global, book-pair scoped (alignment work is reusable across projects whose triaged books overlap)
   - `concept_a_id` TEXT
   - `concept_b_id` TEXT (with constraint: `a.book_id < b.book_id`)
   - `same_concept` BOOLEAN (LLM verdict)
   - `confidence` FLOAT
   - `rationale` TEXT (LLM's brief explanation)
   - `created_at` TIMESTAMP
   - PK `(concept_a_id, concept_b_id)`

**New tools** (3 total):

1. **`list_books(altitude?)`** — corpus introspection. Pure read; trivial.
2. **`start_project(name, project_description, triaged_book_ids?)`** — creates `projects` row. If `triaged_book_ids` is omitted, runs triage internally via the existing `triage_books` flow. Returns `project_id`. Does NOT build the unified KG yet (separate step so `build_project_kg` can run async with progress events).
3. **`build_project_kg(project_id)`** — orchestrates alignment for the project's triaged books. For each pair (A, B) where `A.book_id < B.book_id`:
   - Cosine-shortlist concepts in A vs. B above an embedding threshold
   - Check `concept_alignment_cache` for existing verdicts; for un-cached pairs, send a batch to Claude for adjudication
   - Cluster aligned concepts into `canonical_concepts` rows; set `role` based on whether any member maps to a Ch. 12 pattern
   - Compute `canonical_embedding` as mean of members
   - Set `projects.unified_kg_built_at = now`
   - Idempotent: re-running on a project with `unified_kg_built_at` set is a no-op (or recomputes if a flag is passed)

**New script:**

- `scripts/align_book_pair.py` — populates `concept_alignment_cache` for a given pair of book_ids. Reusable by `build_project_kg` (which calls it on demand for un-cached pairs) and runnable standalone by an operator who wants to pre-warm the cache before the first project consultation.

### Sub-staging (hybrid execution order — locked)

| Stage | Scope |
|---|---|
| **3a** | Schema + DB helpers + `list_books` tool. Add `projects`, `canonical_concepts`, `concept_alignment_cache` tables to `db.py`. New helpers: `create_project`, `get_project`, `list_projects`, `upsert_canonical_concept`, `get_alignment_decision`, `record_alignment_decision`. Register `list_books` in `server.py` (4-place edit). New `tests/test_projects_schema.py`. Single-book corpus is fine for this stage; nothing here exercises cross-book alignment. |
| **3b** | `start_project` tool. New `src/iconsult_mcp/tools/projects.py`. Internal triage via existing `triage_books` when `triaged_book_ids` omitted. Tests verify project creation, idempotent re-runs by id, triage fallback path. Still single-book. |
| **(inline)** | **Second-book ingestion.** Pause Phase 3. Pick a mid-level pattern book (Hohpe EIP / Nygard *Release It!* / Fowler), run it through Mathpix → markdown, add a `BOOKS` registry entry, run `seed_books_table.py` and `run_pipeline.py --book <new_id>`, generate + commit its summary via `generate_book_summary.py`. After this stage the corpus has 2 books. ~30-60 min wall time + real API cost. Note: this is *only the ingestion portion* of Phase 6. The "run a real consultation, compare to single-book baseline" portion stays at the final merge gate after Phases 4 and 5. |
| **3c** | `align_book_pair.py` + `build_project_kg` tool — now against real two-book data. Claude adjudication prompt design, batched LLM calls, alignment-cache reuse, role classification (supporting_evidence vs. informational_only based on rubric alias hits), canonical embedding computation. Manual review of a sample of canonical clusters confirms quality. |
| **3d** | Phase 3 verification + commit. End-to-end: `start_project(...)` → `build_project_kg(project_id)` → inspect canonical_concepts, concept_alignment_cache for both real books. Update `CLAUDE.md`. Push. |

## Files that will change

- **MODIFY** `src/iconsult_mcp/db.py` — new tables in `ensure_schema()`; new helpers
- **NEW** `src/iconsult_mcp/tools/projects.py` — `list_books`, `start_project`, `build_project_kg`
- **MODIFY** `src/iconsult_mcp/server.py` — register 3 tools (4-place edit each)
- **NEW** `scripts/align_book_pair.py`
- **NEW** `tests/test_projects_schema.py`
- **NEW** `tests/test_projects.py`
- **NEW** `tests/test_alignment.py`
- **MODIFY** `tests/conftest.py` — likely gains a project-cleanup fixture analogous to the existing `consultation_cleanup` (delete project / canonical_concepts / alignment_cache rows tagged with test markers)
- **MODIFY** `CLAUDE.md` — tools list, schema list, mention Phase 3 work

## Reuse — don't reinvent

- `embed_query()` (Phase 2): same OpenAI wrapper. Used for canonical embedding mean computation? No — canonical embeddings are computed as the mean of member embeddings already in `concept_embeddings`. No new embedding calls needed for clustering.
- `claude_messages()` (existing): used for alignment adjudication. Batch concepts in groups of ~10–20 per prompt to amortize per-call overhead.
- `search_books_by_embedding` (Phase 2b): used internally by `start_project` when triaged_book_ids is omitted. Already deterministic.
- `search_concepts_by_embedding` (Phase 1): already accepts `book_id` filter — extend with optional `exclude_book_id` or call twice for cross-book shortlisting. Don't duplicate query logic.
- `_PATTERN_ID_ALIASES` + `normalize_pattern_id()` in `rubric_data.py`: alignment writes new alias entries here for non-Arsanjani concepts that the LLM identifies as Ch. 12 pattern equivalents. **But — Phase 5 wires this into scoring, not Phase 3.** Phase 3 only populates the data; the runtime alias resolution is already book-agnostic. Don't change `score_architecture` here.
- Tool-registration 4-place edit pattern. See how `triage_books` was added in commit `7e860f5`.
- Write-behind step buffer (in `db.py`): if `build_project_kg` logs progress steps to a consultation, it goes through the same buffer. No special handling.

## Verification

```bash
# After 3a:
py -m pytest tests/test_projects_schema.py -v
py -c "from iconsult_mcp.db import list_projects; print(list_projects())"

# After 3b:
py -m pytest tests/test_projects.py -v
# via MCP:
#   start_project(name="test", project_description="multi-agent supervisor architecture")
#   → returns project_id, triaged_book_ids=['arsanjani_2026']

# After second-book ingestion (inline):
py -c "from iconsult_mcp.db import list_books; print([b['id'] for b in list_books()])"
# Expect: ['arsanjani_2026', '<new_book_id>']
#   triage_books("multi-agent supervisor") → both books ranked, scores compared

# After 3c (with two real books in the corpus):
py -m pytest tests/test_alignment.py -v
# alignment_cache populated for the (arsanjani_2026, <new_book_id>) pair
# canonical_concepts span both books with correct role classification

# After 3d:
py -m pytest tests/ -v       # 142 + new tests, all green
# End-to-end:
#   start_project(...) → build_project_kg(project_id)
#   → canonical_concepts spanning both books, sample manually reviewed for cluster quality
```

## Cost / time

- **3a (schema + helpers)**: small, ~1-2 hours
- **3b (`start_project` + `list_books`)**: small, ~1 hour
- **Second-book ingestion (inline)**: ~30-60 min wall time + real API cost (~$5-15 for full pipeline on a mid-level book; depends on book length and chapter count)
- **3c (`build_project_kg` + `align_book_pair.py`)**: largest piece, ~4-6 hours including Claude prompt design and alignment-cache logic; alignment LLM cost depends on number of cosine-shortlisted pairs (~$1-5 for a single book pair)
- **3d (tests + verification)**: medium, ~2-3 hours

Total Phase 3 implementation: **likely two focused sessions** — one to ship 3a/3b + ingest the second book, another to tackle alignment + verification.

## First commands to run in the new session

```bash
git status                                # confirm clean tree
git branch --show-current                 # should be feat/multi-book-kg
git log --oneline -5                      # confirm Phase 2c at top
py -m pytest tests/ -q                    # 142 passing
py -c "from iconsult_mcp.db import get_book; r = get_book('arsanjani_2026'); print('summary:', len(r['summary']), 'has_emb:', r['has_summary_embedding'])"
# Expect: summary: 5145 has_emb: True
```

## Decided — execution order (locked 2026-04-30)

Hybrid: 3a → 3b → second-book ingestion → 3c → 3d. See the matching row in the locked-decisions table above and the sub-staging table.

**Why this order, not synthetic fixtures:** alignment is the one place where the code calls Claude to adjudicate "are these two concepts the same?" Synthetic fixtures are most likely to mislead in exactly that LLM-judgment-heavy step — a hand-crafted fake second book might exercise the code paths but won't surface the kinds of edge cases (vocabulary mismatch across authors, partial overlap, false friends) that real adjudication encounters. Doing 3a/3b first keeps momentum on safe schema + tooling work; pausing to ingest a real second book before 3c gets us real adjudication data when it actually matters.

**Why not pure reorder (Phase 6 first):** the schema and `start_project` work doesn't need a second book and can ship fast. Doing it first also means when we ingest the second book, the project-scoping infrastructure already exists to test against.

**Book-pick decision happens at the start of the inline ingestion stage, not now.** Hohpe EIP, Nygard *Release It!*, and Fowler are all viable; pick whichever has the cleanest Mathpix output and best altitude match.
