# Phase 4 Briefing — Project-Scoped Tool Plumbing

> **For a fresh session.** Read this end-to-end before doing anything. The full plan lives at [`../multi-book-architecture-plan.md`](../multi-book-architecture-plan.md). The active-initiative memory file is `~/.claude/projects/C--Users-marcu-git-repositories-Iconsult-mcp/memory/multi_book_refactor.md`.

## TL;DR

Phase 3 shipped. The corpus has two real books (`arsanjani_2026` + `gulli_2025`), the alignment cache is populated, and `build_project_kg` produces canonical clusters. **Phase 4 threads `project_id` through the consultation tools** so a consultation can scope to a project's canonical layer rather than querying the global concept space. Without Phase 4 the per-project layer exists but nobody uses it during a consultation — `match_concepts` still searches all books, `get_subgraph` still traverses raw edges, etc.

Phase 4 is plumbing-only: no new schema, no new LLM calls, no alignment work. The canonical layer already exists; we're routing reads through it when a `project_id` is supplied. When `project_id` is absent the tools fall back to today's single-book legacy behaviour, so the tool surface stays backwards compatible.

## Where we are

```
feat/multi-book-kg  e3d6612  fix: three more Phase 3c alias gaps companion to FCoT
                    47cbe82  fix: alias arsanjani's fcot_pattern to fractal_cot_embedding
                    38c93bb  Phase 3c: align_book_pair + build_project_kg
                    c322e20  Phase 3 (inline): ingest gulli_2025 + concepts.name unique migration
                    1c06bd3  Phase 3b: start_project tool with internal triage fallback
                    c531523  Phase 3a: per-project canonical layer schema + list_books tool
                    4e4040c  docs: lock Phase 3 hybrid execution order
                    00725d8  Phase 2c
                    7e860f5  Phase 2b
                    fd732e8  Phase 2a
                    9f01bb5  Phase 1 done docs
                    1dd78d6  Phase 1d
                    d63c5c6  Phase 1c
                    b141d98  Phase 1b
                    adf8e45  Phase 1a
main                a69968e
```

Both branches are pushed to `origin`. Local DuckDB at `data/iconsult.duckdb`:

- **2 books** with summaries + 1536-dim summary_embeddings:
  - `arsanjani_2026` (oracle, mid_level): 138 concepts / 786 sections / 583 relationships
  - `gulli_2025` (implementation): 180 concepts / 390 sections / 802 relationships
- **94 alignment-cache rows** (48 same_concept=True), all canonically ordered by concept ID
- 0 projects / 0 canonical_concepts in the DB right now (the demo cluster review project was cleaned up; Phase 3c tests use ephemeral projects with `project_cleanup`)

29 MCP tools registered. Test suite: **199/199** passing.

## Locked design decisions — do not re-litigate

| Topic | Decision |
|---|---|
| Database | Local DuckDB only. Unchanged. |
| Triage signal | Book-summary embeddings (`triage_books`). Unchanged. |
| Unified KG cadence | Cached per-project. Built once via `build_project_kg`. Phase 4 reads from it. |
| Concept role | `supporting_evidence` (rubric-anchored, contributes to scoring in Phase 5) vs `informational_only` (enrich passages/traversal, never score). Both flow through `match_concepts` and `get_subgraph` results when a `project_id` is set; only supporting_evidence reaches `score_architecture`. |
| Backwards compatibility | When `project_id` is omitted from any of the consultation tools, behaviour is **identical to today**. Existing single-book consultations and tests must keep passing without changes. |
| Concept ID surfacing | When project-scoped, tools return *canonical concept IDs* (`{project_id}__{slug}`) rather than book-scoped IDs. `member_concept_ids` is exposed so callers can resolve back to source-book concepts when they need book-specific provenance (e.g., `ask_book` passages, `log_pattern_assessment.source_book_id`). |
| Pattern-ID aliasing | The Phase 5 wiring (`normalize_pattern_id` / `_PATTERN_ID_ALIASES`) is already book-aware and already strips `{book_id}__` prefixes — no change needed in Phase 4. Phase 5 will route assessments logged with canonical IDs through to the rubric. |

## Phase 4 scope

Per the plan: "Tool scoping. `match_concepts` / `get_subgraph` / `ask_book` accept `project_id` and produce project-scoped results. Existing single-book consultations unaffected."

### What's needed concretely

**Modified tools** (4 total):

1. **`match_concepts(project_description, project_id?, ...)`**
   - When `project_id` set AND project's `unified_kg_built_at` is non-null → embed the description, cosine-search `canonical_concepts.canonical_embedding` (filtered by `project_id`), return canonical concepts with `member_concept_ids`, `role`, `rubric_pattern_id`.
   - When `project_id` set but KG not yet built → return error pointing the caller at `build_project_kg`.
   - When `project_id` omitted → existing behaviour (search global `concept_embeddings`).
   - The returned `consultation_id` should also persist `project_id` on the consultation row so downstream tools can pick it up automatically. Add `project_id VARCHAR` to the `consultations` table (per the plan's "Modified tables" section).

2. **`get_subgraph(concept_ids, project_id?, ...)`**
   - When `project_id` set → traverse a *canonical edge view*: for each canonical concept ID in `concept_ids`, expand to its `member_concept_ids`, run the existing priority-queue BFS over the source `relationships` rows, then map every node back to its canonical cluster (de-duplicating cross-book duplicates). Edges between two canonical concepts collapse if multiple source-book edges exist between them; pick the highest-confidence one.
   - When `project_id` omitted → existing behaviour.
   - This is the trickiest piece — there are real design choices about edge merging. See **Open question** below.

3. **`ask_book(question, project_id?, ...)`**
   - When `project_id` set → scope passage search to sections from the project's `triaged_book_ids`. Cleanest implementation: expand canonical concept IDs (if supplied via `concept_ids`) to their `member_concept_ids`, then call the existing `search_sections_by_embedding` with that expanded set.
   - When `project_id` omitted → existing behaviour (all books).

4. **`log_pattern_assessment(..., source_book_id?, canonical_concept_id?)`**
   - Add two optional fields to `step_data` for provenance: `source_book_id` (which book the pattern evidence came from) and `canonical_concept_id` (the canonical cluster the assessed concept belongs to, when project-scoped). No behaviour change — `score_architecture` still keys on `pattern_id` resolved through the rubric aliases.
   - Smaller piece; leave for last.

**Schema additions:**

- `consultations.project_id VARCHAR` (nullable; NULL for legacy consultations).
- Migration helper analogous to `_migrate_concepts_name_unique`: `_migrate_consultations_add_project_id` runs from `_init_schema`, idempotent. Or just an `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` (DuckDB supports the silent-add pattern via try/except, which is what the existing schema migrations already use).

**No new MCP tools** — Phase 4 only modifies existing ones.

### Sub-staging proposal (locked at the start of the session unless we hit an obstacle)

| Stage | Scope | Cost |
|---|---|---|
| **4a** | Schema: `consultations.project_id` column + migration. `match_concepts(project_description, project_id?)` accepts the param, persists it on the consultation row, routes to `canonical_concepts.canonical_embedding` search when project KG is built. New `db.search_canonical_concepts_by_embedding`. Tests in `tests/test_match_concepts_project_scoped.py`. **Side benefit**: `tests/cases.py` can lock to single-book scope (no project_id), eliminating the test-fixture drift problem that bit us at the gulli ingestion. | Small, ~2-3 hours. |
| **4b** | `get_subgraph(concept_ids, project_id?)` — canonical edge view. New `db.get_canonical_subgraph` that expands canonical IDs → member IDs, traverses, collapses to canonical clusters. Edge confidence: max-of-source-edges. This is the meatiest piece. | Medium, ~3-4 hours including tests. |
| **4c** | `ask_book(question, project_id?, concept_ids?)` — passage search scoped to triaged books with canonical-concept expansion. Likely a small change since `search_sections_by_embedding` already accepts a `concept_ids` filter. | Small, ~1-2 hours. |
| **4d** | `log_pattern_assessment(..., source_book_id?, canonical_concept_id?)` — provenance fields. Update step_data schema, `_get_pattern_assessments` reader, downstream consumers (failure_scenarios, render_report). | Small, ~1-2 hours. |
| **4e** | End-to-end project-scoped consultation walkthrough on the live arsanjani+gulli corpus. Manually run `start_project` → `build_project_kg` → `match_concepts(..., project_id=...)` → `get_subgraph(..., project_id=...)` → `ask_book(..., project_id=...)` → log a few assessments → `score_architecture` and verify it still produces a sane scorecard with non-arsanjani assessments contributing as supporting_evidence. Update `CLAUDE.md`, plan tracking, push. | Medium, ~2-3 hours including manual review. |

Total: **likely one focused session** for 4a–4d (mostly mechanical), plus a second session for 4e end-to-end review and cleanup if needed.

## Files that will change

| File | Change |
|---|---|
| `src/iconsult_mcp/db.py` | New table column `consultations.project_id` (with migration helper). New helpers: `search_canonical_concepts_by_embedding`, `get_canonical_subgraph` (or extend the existing `get_subgraph` helper to accept project mode). |
| `src/iconsult_mcp/tools/match_concepts.py` | Optional `project_id` arg; route to canonical search when project's KG is built. |
| `src/iconsult_mcp/tools/get_subgraph.py` | Optional `project_id` arg; route to canonical traversal when set. |
| `src/iconsult_mcp/tools/ask_book.py` | Optional `project_id` arg; expand canonical concept IDs when supplied; scope sections to triaged books. |
| `src/iconsult_mcp/tools/log_pattern_assessment.py` | Optional `source_book_id`, `canonical_concept_id` fields in step_data. |
| `src/iconsult_mcp/server.py` | Add `project_id` (and the new optional args) to the four tools' input schemas + dispatch. **No new tool registrations.** |
| `tests/test_match_concepts_project_scoped.py` | NEW. |
| `tests/test_get_subgraph_project_scoped.py` | NEW. |
| `tests/test_ask_book_project_scoped.py` | NEW. |
| `tests/cases.py` | Possibly: pass `project_id=None` explicitly so cases.py reads naturally as "single-book mode". Optional. |
| `CLAUDE.md`, `docs/multi-book-architecture-plan.md` | Update tools list and Implementation Tracking. |

## Reuse — don't reinvent

- **`canonical_concepts.canonical_embedding`** is already populated by Phase 3c with mean-of-members embeddings. `match_concepts` project-scoped path is a near-clone of `db.search_concepts_by_embedding` against this table; copy the structure rather than rolling new SQL.
- **`canonical_concepts.member_concept_ids`** is the bridge from canonical → source. Use it everywhere you need to translate between layers.
- **`get_book(book_id)`** + **`projects.triaged_book_ids`** give you the "which books does this project span?" data for `ask_book` scoping and for safety-checking that a `concept_id` actually belongs to the project.
- **`canonical_concepts.role`**: Phase 5 will read this to filter scoring (only supporting_evidence flows in). Phase 4 just exposes it through tool responses; no behaviour change tied to role.
- **Existing `consultation_id` plumbing** in match_concepts → get_subgraph → ask_book is unchanged. Add `project_id` alongside, persisted to `consultations.project_id` once on `match_concepts`, picked up automatically by downstream tools when not explicitly provided. Avoid asking the caller to pass `project_id` to every tool — it should ride on the consultation.
- **The pipeline output buffering bug**: `py -u` is required when running long pipeline scripts redirected to a log file. Bit us during Phase 3 ingestion — make this the default in any new long-running scripts (none expected in Phase 4).

## Open question — `get_subgraph` canonical edge view

**The design choice that needs an answer in 4b**:

When traversing the canonical view, a single edge between two canonical concepts can correspond to multiple source-book edges (e.g., A1—uses—B1 from arsanjani plus A2—uses—B2 from gulli, where {A1, A2} share a canonical cluster and {B1, B2} share another). What does the canonical edge look like?

Three options:
1. **Max-confidence collapse**: pick the highest-confidence source edge as the canonical edge. Fast, simple, slightly lossy on relationship_type when source edges disagree.
2. **Multi-edge per relationship_type**: emit one canonical edge per distinct (relationship_type) across source edges. Preserves nuance, but `get_subgraph` callers may see "duplicate" edges with different types.
3. **Voted relationship_type + averaged confidence**: bucket by relationship_type, pick the most common, average the confidences. More work, smoother results.

Recommendation: **option 1 first** (cheap, gets us to working). Only escalate to option 2 if we hit a real consultation case where collapsed edges hide useful information.

## Verification

```bash
# After 4a:
py -m pytest tests/test_match_concepts_project_scoped.py -v
# Manually:
#   start_project(name="x", project_description="agentic supervisor with reflection")
#   build_project_kg(project_id=...)
#   match_concepts(project_description="...", project_id=...) → returns canonical IDs

# After 4b:
py -m pytest tests/test_get_subgraph_project_scoped.py -v
# Manually:
#   get_subgraph(concept_ids=[<canonical id>], project_id=...) → cross-book edges visible

# After 4c:
py -m pytest tests/test_ask_book_project_scoped.py -v
# Manually:
#   ask_book(question, concept_ids=[<canonical>], project_id=...) → passages from triaged books only

# After 4d:
# Manually log_pattern_assessment with source_book_id="gulli_2025" + canonical_concept_id=...
# verify step_data carries provenance and score_architecture still anchors via aliases.

# After 4e (end-to-end):
py -m pytest tests/ -v   # 199 + new tests, all green
# Manual run: complete consultation on arsanjani+gulli project, validate scorecard reflects
# both books' assessments via supporting_evidence routing.
```

## Cost / time

- **4a**: small, ~2-3 hours (schema + match_concepts + tests)
- **4b**: medium, ~3-4 hours (canonical edge view is the trickiest piece)
- **4c**: small, ~1-2 hours
- **4d**: small, ~1-2 hours
- **4e**: medium, ~2-3 hours (end-to-end manual run + docs + push)

No LLM-call costs in Phase 4 itself. The arsanjani+gulli alignment cache is already populated, so any project-scoped `build_project_kg` runs during testing are cache hits.

Total Phase 4 implementation: **likely one focused session**, with 4e potentially spilling into a second session for thorough end-to-end review.

## First commands to run in the new session

```bash
git status                                # confirm clean tree
git branch --show-current                 # should be feat/multi-book-kg
git log --oneline -8                      # confirm e3d6612 at top
py -m pytest tests/ -q                    # 199 passing
py -c "from iconsult_mcp.db import get_book; print('books:', [b['id'] for b in __import__('iconsult_mcp.db', fromlist=['list_books']).list_books()])"
# Expect: ['arsanjani_2026', 'gulli_2025']
py -c "from iconsult_mcp.db import get_connection; print('alignment cache rows:', get_connection().execute('SELECT COUNT(*) FROM concept_alignment_cache').fetchone()[0])"
# Expect: 94
```

## After Phase 4

Phase 5 wires the scoring path: non-arsanjani assessments contribute to the rubric via aliases. Phase 6 is the final merge gate — run a real consultation on a 2-book project and compare the report quality to the single-book baseline. Both phases are downstream of Phase 4's plumbing.
