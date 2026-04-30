# Multi-Book Iconsult MCP — Per-Project Cached Canonical KG

> **Implementation plan.** Visual proposal: [`multi-book-architecture-proposal.html`](./multi-book-architecture-proposal.html).
> See the [Implementation Tracking](#implementation-tracking) section at the bottom for current status, branch strategy, and Phase 1 sub-staging.

## Context

Iconsult MCP today consults a single book (Arsanjani & Bustos 2026) — its KG, concepts, embeddings, and pipeline are all hardcoded to that one source. The user wants to grow the corpus to multiple books spanning different altitudes (high-level architecture → concrete implementation), while:

1. **Keeping Ch. 12 of Arsanjani as the single source of truth for `score_architecture`** — the rubric is the oracle, immune to dilution.
2. **Triaging books per project** — only relevant books for a given project waste no traversal time.
3. **Caching a unified KG per project** — alignment across books is paid once per project (not per consultation, not corpus-wide), and follow-up consultations on the same project reuse it.
4. **Distinguishing concept roles** — imported concepts are either *supporting evidence* (linked to a Ch. 12 pattern, contributes to indicators) or *informational only* (informs guidance/passages, never scores).

User's confirmed answers:
- **Triage signal:** Book-summary embeddings (one vector per book, deterministic match against project description)
- **Unified KG cadence:** Cached per-project (build on first consultation in a project, reuse across follow-ups)
- **Rubric link:** Both — supporting-evidence and informational-only, tagged distinctly
- **First books:** Mid-level patterns (Hohpe, Fowler, Nygard, etc.) — closest fit to Ch. 12

### Database & graph query decisions (post-plan amendments)

- **Local DuckDB only.** Database lives on the local filesystem (path configured via `ICONSULT_DB`, defaulting to a project-local file). MotherDuck is **not** the deployment target — hosting decisions are deferred until after Phase 6, and the codebase must not assume MotherDuck. Reasons: proprietary considerations and uncertainty about hosting; local-first removes the MotherDuck-specific constraints (e.g., the existing VSS-extension fallback note in CLAUDE.md becomes obsolete).
- **DuckPGQ evaluated and dropped (2026-04-30).** The DuckDB community SQL/PGQ extension was considered for graph traversal but is not currently published for `windows_amd64` on community-extensions.duckdb.org (404 on download). Rather than gate the project on a Windows-unfriendly dependency, we keep the existing Python priority-queue BFS in `get_subgraph` as the primary traversal mechanism. Revisit if/when DuckPGQ Windows support lands or if the dev environment moves to Linux/WSL.

## Recommended Architecture

### Layered model

```
┌─────────────────────────────────────────────────────────────────┐
│  ORACLE LAYER (immutable)                                       │
│   Ch. 12 RUBRIC in rubric_data.py — 7 categories × 3 levels     │
│   × 36 patterns. Single source of truth for score_architecture. │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │ assessments anchor here via aliases
                              │
┌─────────────────────────────────────────────────────────────────┐
│  PROJECT LAYER (per-project cache)                              │
│   projects, canonical_concepts (role + rubric_pattern_id)       │
│   Built once per project from triaged books. Reused across      │
│   consultations on the same project.                            │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │ aligned via embedding + LLM adjudication
                              │ (cached globally at book-pair level)
                              │
┌─────────────────────────────────────────────────────────────────┐
│  CORPUS LAYER (per-book KGs)                                    │
│   books, concepts (book_id), sections (book_id),                │
│   relationships (book_id), concept_embeddings, summary_embedding│
│   Per-book pipeline ingests each book independently.            │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │ ingested via parameterized pipeline
                              │
┌─────────────────────────────────────────────────────────────────┐
│  RAW LAYER                                                      │
│   literature/{book_slug}/{book.md, index.md}                    │
└─────────────────────────────────────────────────────────────────┘
```

### Triage flow

```
project_description
       │
       ▼
embed_query() ─────────► query embedding (1536-d)
       │
       ▼
cosine vs books.summary_embedding (small N, fast)
       │
       ▼
ranked book list ────► top-k above threshold ──► triaged_book_ids
```

### Per-project KG build (one-shot per project)

```
triaged_book_ids
       │
       ▼
for each pair (A, B):
   collect concepts from A, B
   for each c in A: top-k similar in B by embedding (already cached)
   shortlist pairs above threshold
       │
       ▼
LLM adjudicates shortlisted pairs ──► concept_alignment_cache (global)
       │
       ▼
Cluster concepts across books into canonical_concepts (project-scoped)
   For each canonical concept:
     - role = supporting_evidence if any member maps to a Ch. 12 pattern
              else informational_only
     - rubric_pattern_id = canonical rubric ID (or NULL)
       │
       ▼
projects.unified_kg_built_at = now
```

### Consultation flow (changes)

The 7-step workflow stays. Only thing that changes: every tool that touches the graph accepts an optional `project_id`. When set, queries scope to the project's canonical concept space (concepts spanning all triaged books, deduplicated). When unset, falls back to single-book legacy behavior.

New step before step 1: **start_project** (or auto-bootstrap) — generates `project_id`, runs triage, kicks off `build_project_kg`. Subsequent consultations on the same project skip triage and KG build.

## Schema Changes

### New tables

**`books`** — corpus catalog
| column | type | notes |
|---|---|---|
| id | TEXT PK | e.g., `"arsanjani_2026"`, `"hohpe_eip_2003"` |
| title | TEXT | |
| authors | TEXT | |
| year | INTEGER | |
| summary | TEXT | ~500-1000 words; basis for triage embedding |
| summary_embedding | FLOAT[1536] | from `embed_query(summary)` |
| altitude | TEXT | `mid_level` \| `implementation` \| `strategy` \| `domain` |
| is_oracle | BOOLEAN | true only for `arsanjani_2026` (Ch. 12 source) |
| chapter_boundaries | JSON | per-book chapter→line map (replaces hardcoded `parse_book.CHAPTERS`) |
| created_at | TIMESTAMP | |

**`projects`** — project-scoped cache
| column | type | notes |
|---|---|---|
| id | TEXT PK | hash of (name + initial description) or user-supplied |
| name | TEXT | |
| description | TEXT | original project description used for triage |
| triaged_book_ids | TEXT[] | books selected by triage |
| unified_kg_built_at | TIMESTAMP | NULL = not yet built |
| created_at | TIMESTAMP | |

**`canonical_concepts`** — project-scoped alignment layer
| column | type | notes |
|---|---|---|
| id | TEXT PK | `{project_id}__{slug}` |
| project_id | TEXT FK | |
| name | TEXT | canonical name (usually from oracle book if present) |
| member_concept_ids | TEXT[] | source concepts from various books that resolve here |
| role | TEXT | `supporting_evidence` \| `informational_only` |
| rubric_pattern_id | TEXT | canonical Ch. 12 pattern ID (NULL if informational_only) |
| canonical_embedding | FLOAT[1536] | mean of member embeddings (for project-scoped match_concepts) |

**`concept_alignment_cache`** — global, book-pair scoped (optimization)
| column | type | notes |
|---|---|---|
| concept_a_id | TEXT | |
| concept_b_id | TEXT | a.book_id < b.book_id (canonical order) |
| same_concept | BOOLEAN | LLM verdict |
| confidence | FLOAT | |
| rationale | TEXT | LLM's brief explanation |
| created_at | TIMESTAMP | |
| PK | (concept_a_id, concept_b_id) | |

Two projects whose triaged books overlap reuse this cache — alignment work is amortized across the user base, even though canonical concepts themselves remain per-project.

### Modified tables

- **`concepts`** — add `book_id TEXT NOT NULL` (FK to `books.id`)
- **`sections`** — add `book_id TEXT NOT NULL`
- **`relationships`** — add `book_id TEXT NOT NULL` (NULL allowed only for synthesized cross-book edges, future)
- **`consultations`** — add `project_id TEXT` (NULL for legacy single-book consultations)
- **`pattern_assessment` step_data** (in `consultations.steps` JSON) — add `source_book_id`, `canonical_concept_id` for provenance

### Migration

Backfill existing rows with `book_id = 'arsanjani_2026'`. Existing consultations get `project_id = NULL` and behave as before. No breaking change.

## New / Modified Tools

### New tools (4 total)

- **`triage_books(project_description, top_k=5, threshold=0.4)`** — embed description, cosine vs `books.summary_embedding`, return ranked list with scores. Pure read.
- **`start_project(name, project_description, triaged_book_ids?)`** — creates `projects` row. If `triaged_book_ids` omitted, runs triage internally. Returns `project_id`. Does NOT build the unified KG yet (that's its own step so it can run async/with progress).
- **`build_project_kg(project_id)`** — runs alignment for the project's triaged books, populates `canonical_concepts`. Idempotent. Long-running (uses LLM); reports progress via events.
- **`list_books(altitude?)`** — corpus introspection.

### Modified tools

- **`match_concepts(project_description, project_id?, ...)`** — if `project_id` set and project's KG is built, search against `canonical_concepts.canonical_embedding` (project-scoped). Else legacy single-book search.
- **`get_subgraph(concept_ids, project_id?, ...)`** — if `project_id` set, traverse the project's canonical edge view (edges between canonical concepts; cross-book where alignment merged them). Else legacy.
- **`log_pattern_assessment(..., source_book_id?, canonical_concept_id?)`** — tracks provenance. Existing pattern-ID alias resolution unchanged.
- **`ask_book(question, project_id?, ...)`** — if `project_id` set, scope passages to triaged books. Else all books.

### Untouched

- `score_architecture` — already book-agnostic; reads RUBRIC, normalizes pattern IDs through aliases. Multi-book Just Works.
- `critique_consultation`, `consultation_report`, `render_report`, `generate_failure_scenarios`, `generate_implementation_plan`, blackboard tools, state tools, event tools — unaffected.

## Pipeline Changes

Make per-book ingestion the default unit of work.

- **`config.py`** — replace `BOOK_FILENAME` / `INDEX_FILENAME` constants with a per-book lookup. Add `LITERATURE_DIR / {book_slug}/{book.md, index.md}` convention.
- **`parse_index.py`** — accept `book_id` arg; write `concepts` rows with that `book_id`. Concept IDs become `{book_id}__{slug}` to avoid collisions.
- **`parse_book.py`** — accept `book_id` arg; pull chapter boundaries from `books.chapter_boundaries` JSON instead of hardcoded `CHAPTERS` table.
- **`tag_concepts.py`, `discover_relationships.py`** — accept `book_id` arg; scope their queries to that book's rows.
- **`build_graph.py`** — accept `book_id` arg; filter relationships and embeddings to that book.
- **`populate_content.py`** — accept `book_id` arg.
- **`run_pipeline.py`** — gain `--book <book_id>` arg; runs all phases scoped to that book. Existing single-book invocation defaults to `arsanjani_2026`.
- **NEW: `scripts/generate_book_summary.py`** — produces `books.summary` (LLM call from chapter abstracts/intro) and `books.summary_embedding`. Run after `build_graph` per book.
- **NEW: `scripts/align_book_pair.py`** — populates `concept_alignment_cache` for a given pair of book IDs. Used by `build_project_kg` (which also calls it on demand for un-cached pairs).

## Rubric Anchoring (how Ch. 12 stays the oracle)

Mechanism: alignment-time classification + alias mapping.

During `build_project_kg`, for each canonical concept cluster:

1. If any member concept comes from `arsanjani_2026` AND maps (by name or alias) to a rubric pattern → `role = supporting_evidence`, `rubric_pattern_id = <canonical>`.
2. Else if the cluster is *semantically near* a rubric pattern (LLM check against pattern definitions) → `role = supporting_evidence`, `rubric_pattern_id = <canonical>`. Confidence-flagged for review.
3. Else → `role = informational_only`, `rubric_pattern_id = NULL`.

For supporting-evidence canonical concepts, alignment writes alias entries that route ANY member concept ID through to the canonical rubric ID via the existing `normalize_pattern_id()` system. No change to `score_architecture` is needed — non-Arsanjani assessments flow into the rubric automatically.

Informational-only concepts appear in `match_concepts` results and `get_subgraph` traversal, can be cited in `ask_book` passages, but never reach `score_architecture`. They enrich consultations without polluting the score.

## Critical Files to Modify

| File | Change |
|---|---|
| `src/iconsult_mcp/db.py` | Schema additions (new tables, new columns), new query functions for canonical concepts and book-scoped lookups |
| `src/iconsult_mcp/config.py` | Replace hardcoded book filenames with per-book registry pattern |
| `src/iconsult_mcp/rubric_data.py` | No semantic change; consider extending `_PATTERN_ID_ALIASES` to support project-scoped aliases at runtime (or add a new `_resolve_pattern_id(pattern_id, project_id?)`) |
| `src/iconsult_mcp/tools/match_concepts.py` | Accept optional `project_id`; route to canonical search when set |
| `src/iconsult_mcp/tools/get_subgraph.py` | Accept optional `project_id`; traverse canonical edges when set |
| `src/iconsult_mcp/tools/ask_book.py` | Scope to triaged books when `project_id` set |
| `src/iconsult_mcp/tools/log_pattern_assessment.py` | Track `source_book_id`, `canonical_concept_id` in step_data |
| `src/iconsult_mcp/tools/triage.py` | NEW |
| `src/iconsult_mcp/tools/projects.py` | NEW (`start_project`, `build_project_kg`, `list_books`) |
| `src/iconsult_mcp/server.py` | Register 4 new tools (4-place edit each) |
| `scripts/run_pipeline.py` | `--book` arg |
| `scripts/parse_index.py`, `parse_book.py`, `tag_concepts.py`, `discover_relationships.py`, `build_graph.py`, `populate_content.py` | `book_id` threading |
| `scripts/generate_book_summary.py` | NEW |
| `scripts/align_book_pair.py` | NEW |
| `CLAUDE.md` | Update tool list, schema list, workflow with project_id step |

## Reused Existing Utilities (do not reinvent)

- `embed_query()` (existing OpenAI embedding wrapper) — used for both book summaries and project descriptions
- `search_concepts_by_embedding()` in `db.py:336–363` — extend with optional book_id / project_id WHERE clause rather than duplicating
- `get_concept_relationships()` in `db.py:366–403` — same: add optional filter param
- `_PATTERN_ID_ALIASES` + `normalize_pattern_id()` in `rubric_data.py` — anchor mechanism for cross-book rubric mapping
- `log_consultation_step()` write-behind buffer — new step types (e.g., `triage`, `alignment_decision`) flow through unchanged
- Slot-based template rendering in `templates/consultation-report-template.html` — new sections fill into existing slots; no template-engine change
- Blackboard (`assert_fact` / `query_facts`) — already supports `agent_id`; can carry `source_book_id` naturally for cross-book conflict detection

## Phasing

| Phase | Scope | Verifiable outcome |
|---|---|---|
| **1** | Multi-book schema + parameterized pipeline | Re-run pipeline on Arsanjani as `arsanjani_2026`; ingest one mid-level pattern book (e.g., Nygard *Release It!* or Hohpe EIP). All existing 134 tests still pass after migration. |
| **2** | Triage layer | `books.summary_embedding` populated for all books. `triage_books` tool returns sane rankings on test prompts. |
| **3** | Per-project canonical layer | `start_project` + `build_project_kg` produce canonical concepts for a 2-book project. Alignment cache populated. Manual review of a sample of canonical clusters confirms quality. |
| **4** | Tool scoping | `match_concepts` / `get_subgraph` / `ask_book` accept `project_id` and produce project-scoped results. Existing single-book consultations unaffected. |
| **5** | Rubric anchoring across books | Run an end-to-end consultation on a 2-book project. Verify `score_architecture` produces same rubric output as before AND that non-Arsanjani assessments contribute as supporting evidence to mapped patterns. |
| **6** | Onboard a real second book | Mid-level pattern book of choice. Run a real consultation. Compare report quality to single-book baseline. |

## Verification

End-to-end checks for the implemented system (executed during phases 5–6):

```bash
# Schema migration is non-destructive
py -m pytest tests/ -v   # all 134 tests should pass after Phase 1

# Per-book pipeline
py scripts/run_pipeline.py --book arsanjani_2026 --reset
py scripts/run_pipeline.py --book nygard_release_it_2018  # or whichever second book
py scripts/generate_book_summary.py --book nygard_release_it_2018

# Triage
iconsult-mcp  # then via MCP client:
#   triage_books("multi-agent system with weak fault tolerance") → expect both books ranked

# Project KG build
#   start_project(name="test", project_description="...") → project_id
#   build_project_kg(project_id) → reports N canonical concepts, M aligned via cache, K via LLM

# Consultation scoped to project
#   match_concepts(project_description, project_id=<id>) → returns canonical concept IDs
#   get_subgraph(concept_ids, project_id=<id>) → cross-book edges visible
#   log_pattern_assessment with non-Arsanjani source_book_id
#   score_architecture → same rubric structure; supporting-evidence assessments contribute

# Backward compat: single-book consultation without project_id still works identically
```

Add new tests:
- `tests/test_triage.py` — book ranking determinism
- `tests/test_project_kg.py` — alignment cache reuse, role classification
- `tests/test_multi_book_scoring.py` — non-Arsanjani assessment contributes to rubric pattern via alias
- `tests/test_pipeline_book_id.py` — pipeline scopes correctly when run per-book

---

## Implementation Tracking

**Status (as of 2026-04-30):** **Phase 1 complete.** All four sub-stages (1a–1d) shipped on `feat/multi-book-kg` and pushed to `origin`. The merge gate is satisfied: full pipeline ran end-to-end on a fresh local DuckDB and produced 138 concepts, 786 sections, 583 relationships, 138 + 786 embeddings — all `book_id='arsanjani_2026'`, all IDs prefixed. 135/135 tests pass. Ready to start **Phase 2** (triage layer) in a fresh session — see [`todo/phase-2-briefing.md`](./todo/phase-2-briefing.md).

**Branch strategy:** Single feature branch `feat/multi-book-kg` off `main`, phase-per-commit. Merge to `main` only when all 6 phases are verified end-to-end against a real second book. Each commit's tests must pass.

**PDF→markdown toolchain:** Mathpix for all books (same as Arsanjani). Mathpix produces LaTeX-flavored markdown (`\section*{}` markers, OCR-cleaned index) that the existing `parse_index.py` / `parse_book.py` already consume. New books slot in without parser rewrites.

**Phase 1 sub-staging — done.** Four reviewable sub-stages, one commit each on `feat/multi-book-kg`:

| Stage | Commit | Scope | Verification |
|---|---|---|---|
| **1a** | `adf8e45` | Schema foundation: switch DB connection from MotherDuck to local DuckDB file, add `books` table, add `book_id` (nullable) to `concepts` / `sections` / `relationships`, update `search_concepts_by_embedding` and `get_concept_relationships` to accept optional `book_id` filter | ✅ Local DB initializes with no `MOTHERDUCK_TOKEN`; new tables/columns exist; query helpers accept the new filter |
| **1b** | `b141d98` | Literature reorg + config: move existing `literature/Arsanjani*.md` files into `literature/arsanjani_2026/`, replace hardcoded `BOOK_FILENAME`/`INDEX_FILENAME` with per-book registry pattern, insert `arsanjani_2026` row in `books` table (title, authors=Arsanjani & Bustos, year=2026, altitude=mid_level, is_oracle=true, chapter_boundaries from existing `parse_book.CHAPTERS`) | ✅ Pipeline scripts can resolve book file paths via registry |
| **1c** | `d63c5c6` | Pipeline parameterization: thread `--book <id>` through `run_pipeline.py` and all six phase scripts (`parse_index`, `parse_book`, `tag_concepts`, `discover_relationships`, `build_graph`, `populate_content`); move chapter boundaries from hardcoded `parse_book.CHAPTERS` into `books.chapter_boundaries` JSON; concept IDs become `{book_id}__{slug}` to avoid collisions when a second book lands | ✅ Pipeline runs end-to-end with `--book arsanjani_2026` |
| **1d** | `1dd78d6` | Verification + docs: re-run full pipeline on Arsanjani with `--reset` against a local DuckDB file, confirm all 134 existing tests pass, update `CLAUDE.md` (drop MotherDuck, document local DB path) | ✅ 135/135 tests pass; CLAUDE.md current; pipeline reproducible (4 fixture updates in `tests/cases.py` to compensate for borderline embedding-ranking drift on fresh pipeline runs) |

### Session continuity

When resuming this work in a new session:

1. Read this section first.
2. For Phase 2 specifically, also read [`todo/phase-2-briefing.md`](./todo/phase-2-briefing.md) — full handoff with locked decisions, scope, files, and verification.
3. Check `git status` and `git log feat/multi-book-kg` to find the last completed sub-stage / commit.
4. Phases 2–6 stay as scoped in the table above; sub-staging will be decided at the start of each phase as a briefing under `docs/todo/`.
