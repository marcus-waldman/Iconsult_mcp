# Iconsult MCP

Multi-agent architecture consultant MCP server backed by per-book knowledge graphs from a three-book corpus: *"Agentic Architectural Patterns for Building Multi-Agent Systems"* (Arsanjani & Bustos, Packt 2026 — oracle/rubric source), *"Agentic Design Patterns"* (Gulli, 2025), and *"Essential GraphRAG"* (Bratanič & Hane, Manning 2025).

## Architecture
- Python MCP server using stdio transport
- Local DuckDB for knowledge graph storage (file path configurable via `ICONSULT_DB`)
- OpenAI embeddings (text-embedding-3-small, 1536 dims) via raw urllib (no httpx)
- Claude API for extraction tasks via raw urllib
- `src/iconsult_mcp/` layout with hatchling build
- Tools: `tools/health.py`, `tools/match_concepts.py`, `tools/triage.py`, `tools/projects.py`, `tools/list_concepts.py`, `tools/get_subgraph.py`, `tools/ask_book.py`, `tools/consultation_report.py`, `tools/score_architecture.py`, `tools/log_pattern_assessment.py`, `tools/validate_subagent.py`, `tools/critique_consultation.py`, `tools/shared_state.py`, `tools/events.py`, `tools/plan_consultation.py`, `tools/supervise_consultation.py`, `tools/failure_scenarios.py`, `tools/implementation_plan.py`, `tools/blackboard.py`, `tools/quality.py`, `tools/render_report.py`, `tools/rubric_data.py`
- L4 modules: `access_policy.py` (tool access levels + consultation ownership validation)
- Rubric data: `rubric_data.py` holds the Ch. 12 category-based rubric (7 categories × 3 levels × 36 patterns with predefined binary indicators); extracted by `scripts/extract_indicators.py`
- Pattern ID aliasing: `_PATTERN_ID_ALIASES` in `rubric_data.py` bridges old MATURITY_MODEL IDs / KG concept IDs → canonical rubric IDs; `normalize_pattern_id()` resolves to canonical form
- Write-behind buffer: `_step_buffer` in `db.py` buffers `log_consultation_step` calls in memory; auto-flushed by `get_consultation()` / `get_pattern_assessments()` before reads
- Resilience: `escalation.py` (structured error responses), dispatch dict + timeout/retry in `server.py`
- Developer docs: `docs/development.md`

## Key Commands
- `pip install -e .` — install in development mode
- `iconsult-mcp` — run MCP server
- `iconsult-mcp --check` — health check
- `py scripts/seed_books_table.py` — seed the `books` row(s) before first pipeline run
- `py scripts/run_pipeline.py --book arsanjani_2026` — run full pipeline for one book (default `arsanjani_2026`)
- `py -m pytest tests/ -v` — run integration tests (requires OPENAI_API_KEY + ANTHROPIC_API_KEY)
- `py -m pytest tests/test_match_concepts.py -v` — run concept matching tests only
- `py -u scripts/verify_phase4e.py` — Phase 4 end-to-end smoke test against live arsanjani_2026 + gulli_2025 corpus (project setup → KG build → match → traverse → ask → assess with provenance → score). Re-runnable; project_id deterministic from name+description so artifacts persist across runs
- `py -u scripts/verify_phase5c.py` — Phase 5 visual smoke test: drives the same demo consultation through `render_report`, writes HTML to `~/.agent/diagrams/`. Open in a browser to eyeball provenance badges; verify_phase4e.py must run first to populate the consultation

## Testing
- Integration tests in `tests/` — require OPENAI_API_KEY and ANTHROPIC_API_KEY env vars
- Test cases in `tests/cases.py` — 12 architectures derived from openai/openai-agents-python examples
- Adding a test case = adding a dict to `CASES` in `tests/cases.py` (id, description, expected_concepts, pattern_assessments)
- Tests: `test_match_concepts.py` (concept matching quality), `test_subgraph.py` (graph traversal), `test_score_architecture.py` (scoring), `test_failure_scenarios.py` (stress test demos), `test_implementation_plan.py` (plan generation/tracking), `test_consultation_flow.py` (end-to-end), `test_pattern_id_aliases.py` (pattern ID alias resolution), `test_blackboard.py` (blackboard knowledge hub), `test_step_buffer.py` (write-behind buffer), `test_triage.py` (book triage tool), `test_projects_schema.py` (Phase 3a projects + canonical_concepts + concept_alignment_cache schema and helpers), `test_projects.py` (Phase 3b start_project tool: explicit + internal-triage paths, deterministic IDs, idempotency, validation), `test_score_architecture_provenance.py` (Phase 5a per-pattern source_book_id + by_source_book rollup), `test_failure_scenarios_provenance.py` (Phase 5b source_book_id on every scenario, oracle default), `test_render_report_provenance.py` (Phase 5c badge rendering gated on by_source_book)

## Environment Variables
- `OPENAI_API_KEY` — required for embeddings
- `ANTHROPIC_API_KEY` — required for extraction pipeline
- `ICONSULT_DB` — optional local DuckDB path (default `data/iconsult.duckdb`); accepts absolute path, repo-relative path, or `:memory:`

## Config (config.py)
- `TOOL_TIMEOUT_SECONDS` = 30 — default timeout for tool calls
- `TOOL_MAX_RETRIES` = 2 — max retries for retryable tools (ConnectionError, TimeoutError, OSError)
- `TOOL_RETRY_BASE_DELAY` = 1.0 — base delay for exponential backoff (delay = base × 2^attempt)

## Database
- Local DuckDB file at `data/iconsult.duckdb` (override with `ICONSULT_DB`)
- 16 tables + 1 metadata table; multi-book refactor adds `books` (corpus catalogue with summary_embedding for triage, is_oracle flag, chapter_boundaries JSON) plus `book_id` columns on `concepts` / `sections` / `relationships`; Phase 3a adds `projects` (per-project cache with triaged_book_ids and unified_kg_built_at), `canonical_concepts` (project-scoped alignment layer with role + rubric_pattern_id + canonical_embedding), `concept_alignment_cache` (global, book-pair scoped LLM verdicts on whether two concepts are the same)
- Multi-book uniqueness: `concepts.name` is no longer column-level UNIQUE — replaced with composite `UNIQUE(name, book_id)` so the same concept name can coexist in multiple books (Phase 3 alignment is what reconciles them); `_migrate_concepts_name_unique` in `db.py` handles the in-place upgrade for legacy databases (idempotent)
- Concept and section IDs are `{book_id}__{slug}` namespaced; `normalize_pattern_id()` strips the prefix before alias lookup so the rubric stays book-agnostic
- `consultations` tracks reproducible sessions; `consultation_state` shared memory; `consultation_events` reactivity; `implementation_plans` cross-session plans; `blackboard_facts` typed/versioned coordination; `consultation_quality` ratings. Phase 4a adds nullable `consultations.project_id` (idempotent ALTER TABLE migration in `_init_schema`); when set, the Phase 4 read tools route through the project's canonical layer; when NULL, behaviour is identical to legacy single-book consultations
- `sections.content` stores cleaned book text per section (populated by `scripts/populate_content.py`)

## MCP Tools
- `health_check` — server health + graph scope
- `match_concepts(project_description, max_results?, similarity_threshold?, project_id?)` — ENTRY POINT: deterministic embedding match; creates `consultation_id` for session tracking; same description → same ranking. When `project_id` is provided AND the project's unified KG has been built (`build_project_kg`), search runs against the per-project `canonical_concepts.canonical_embedding` layer (deduplicated across triaged books) and matched concepts carry `member_concept_ids`, `role`, and `rubric_pattern_id`; response includes `scope: "project_canonical"`. When `project_id` is omitted, behaviour is identical to the legacy single-book path. Errors when `project_id` references an unknown project or one whose KG has not yet been built. The supplied `project_id` (or NULL) is persisted on the consultations row so downstream Phase 4 tools can pick it up automatically.
- `triage_books(project_description, top_k=5, threshold=0.4)` — TRIAGE: deterministic cosine match against `books.summary_embedding`; ranks registered books by relevance to a project description; pure read tool, no consultation_id created; degenerate while only one book is registered
- `list_books(altitude?)` — BROWSE: list registered books in the corpus catalogue with optional altitude filter; pure read tool
- `start_project(name, project_description, triaged_book_ids?, project_id?, triage_top_k=5, triage_threshold=0.4)` — START PROJECT: create or refresh a per-project cache row; runs `triage_books` internally when `triaged_book_ids` omitted; deterministic project_id from hash of (name, description) when not user-supplied; idempotent on re-run; does NOT build the unified KG
- `build_project_kg(project_id, force=False, auto_align=True, align_threshold=0.6, align_top_k=5)` — BUILD PROJECT KG: aligns each pair of triaged books (cosine-shortlist + Claude adjudication, cached in `concept_alignment_cache`), runs union-find over positive same_concept verdicts to cluster cross-book equivalents, writes one `canonical_concepts` row per cluster (singletons included) with role classification (`supporting_evidence` when any member maps to a Ch. 12 rubric pattern via aliases; `informational_only` otherwise), `rubric_pattern_id`, and a mean-of-members `canonical_embedding`; marks project as built. Idempotent: skips when `unified_kg_built_at` is set unless `force=True` (force=True clears existing canonical_concepts for that project first). Long-running (timeout 600s)
- `list_concepts(search?, include_definitions?)` — BROWSE: compact flat list (id, name, category); use for catalogue browsing, not as consultation entry point
- `get_subgraph(concept_ids, max_hops=2, confidence_threshold=0.5, max_edges=50, include_descriptions?, consultation_id?, project_id?)` — QUERY PLANNER: priority-queue traversal; logs steps when `consultation_id` provided. When the consultation row carries a `project_id` (or `project_id` is passed explicitly here) AND the project's KG is built, traversal runs over the canonical edge view via `db.get_canonical_subgraph` — each canonical seed expands to its source-book members, BFS runs across raw `relationships`, and results collapse back to canonical clusters. Edge collapse is **option 1 (max-confidence)**: one canonical edge per `(from_canonical, to_canonical)` pair, keeping the highest-confidence source edge's `relationship_type` and `confidence`. Intra-cluster source edges (both endpoints in the same canonical) are filtered. Nodes carry `member_concept_ids` / `role` / `rubric_pattern_id`. Project_id is auto-picked up from the consultation row so callers don't have to re-pass it.
- `ask_book(question, concept_ids?, max_passages?, consultation_id?, project_id?)` — DEEP CONTEXT: RAG search; returns `suggested_questions` from graph edges; logs steps when `consultation_id` provided. Passages always carry `book_id` provenance. When the consultation row carries a `project_id` (or `project_id` is passed explicitly here) AND the project's KG is built: caller-supplied canonical `concept_ids` are expanded to `member_concept_ids` before section search (via `_expand_canonical_to_members` against `list_canonical_concepts`); section search additionally scopes to the project's `triaged_book_ids` via the new `book_ids` filter on `search_sections_by_embedding`. Suggested questions derive from the expanded members. Project_id auto-pickup from the consultation row, same pattern as `get_subgraph`.
- `consultation_report(consultation_id, compare_to?)` — COVERAGE CHECK: concept coverage (matched concepts that were traversed OR assessed), relationship type coverage, passage diversity, gap identification, cross-session diff
- `log_pattern_assessment(consultation_id, pattern_id, pattern_name, status, evidence?, maturity_level?, failure_context?, category?, indicators?, source_book_id?, canonical_concept_id?)` — LOG ASSESSMENT: record a pattern assessment during graph traversal; status is "implemented", "partial", "missing", or "not_applicable"; when `indicators` provided (list of `{text, met, na?}`), status auto-computed from indicators; `category` auto-resolved from rubric; optional `failure_context` for stress test demos. Phase 4d: optional `source_book_id` (which book the evidence came from, e.g., "gulli_2025") and `canonical_concept_id` (the canonical cluster the assessed concept belongs to in a project-scoped consultation) for multi-book provenance. Pure attribution — no validation, no behaviour change to score_architecture (still keys on `pattern_id` resolved through rubric aliases). Surfaced through `_get_pattern_assessments` to downstream tools (failure_scenarios, render_report) for free. B7: `category` and `indicators` are now exposed in the MCP `inputSchema` and dispatch lambda (previously the underlying fn accepted them but the MCP surface dropped them silently); MCP callers can drive indicators-driven status auto-computation from the harness, with the `indicators` array decoded by `coerce_typed_args` when the harness ships it as a JSON-encoded string.
- `score_architecture(consultation_id)` — CATEGORY-BASED RUBRIC: deterministic scoring from stored `pattern_assessment` steps; 7 categories (Coordination, Explainability, Robustness, Human-Agent, Agent Capabilities, Infrastructure, Continuous Improvement) × 3 levels (Basic/Intermediate/Advanced) from Ch. 12; each category rated Not Started/Emerging/Established/Mature; binary indicators per pattern; gap analysis with missing indicators; roadmap by category (weakest first). Phase 5a: each entry in `categories[k]["levels"][lv]["patterns"]` carries optional `source_book_id` / `canonical_concept_id` when the underlying assessment supplied them (absent on legacy/single-book consultations — byte-identical output to pre-5a). `overall_summary` gains an optional `by_source_book` rollup counting assessed rubric patterns per source book; emitted only when at least one assessment had provenance, so single-book consultations keep their existing summary shape verbatim. Scoring math is unchanged — provenance is attribution-only. Canonical `overall_summary` keys: `total_patterns_in_rubric`, `total_assessed`, `implemented`, `not_met`, `not_applicable`, `categories_assessed`, `categories_not_started` (no `_patterns` suffix on counts; "missing" is `not_met`).
- `validate_subagent(response, validate_against_graph?)` — VALIDATE: schema validation for subagent JSON responses {concept, key_relationships, recommendation, discovered_ids}; pure structural checks, no LLM; optional `validate_against_graph` verifies discovered_ids exist in concepts table and concept matches a known name (returns semantic_warnings separately)
- `critique_consultation(consultation_id, max_iterations?)` — CRITIQUE: deterministic quality critique of consultation steps; checks workflow completeness, traversal depth, assessment coverage, passage diversity, critical edges; returns issues with severity + `prompt_mutations` for adaptive retry; `max_iterations` (1-3) enables multi-pass critique with convergence/stuck-loop detection
- `write_state(consultation_id, key, value)` — SHARED STATE (write): upsert key-value pair for subagent coordination; logs state_write step
- `read_state(consultation_id, key?)` — SHARED STATE (read): read one key or all entries from shared state
- `emit_event(consultation_id, event_type, data?)` — EVENT (emit): emit consultation event (gap_found, pattern_assessed, coverage_threshold_reached, coverage_dropped, plan_created, state_conflict); returns reactive suggestion
- `get_events(consultation_id, since_id?, event_type?)` — EVENT (poll): poll events with optional filters
- `plan_consultation(consultation_id)` — PLAN: assess complexity (simple/moderate/complex) and generate adaptive step-by-step plan after match_concepts
- `supervise_consultation(consultation_id)` — SUPERVISE: track workflow progress (phases completed/remaining, percent), suggest next action with tool + params, include event alerts and shared state
- `generate_failure_scenarios(consultation_id, max_scenarios?)` — RESILIENCE ANALYSIS: deterministic resilience scenario walkthroughs for patterns not yet in place; each scenario illustrates how the architecture responds under stress (trigger → propagation steps with file:line refs when code available → potential impact); maps Ch. 7 five-step failure chain; notes foundation dependencies when advanced patterns rely on patterns not yet implemented; two modes: code-grounded (from `failure_context.code_refs`) or book-grounded (from pattern scenario templates). Phase 5b: every scenario carries `source_book_id`. When the matching `pattern_assessment` supplied one (e.g., user logged a `missing` assessment with `source_book_id="gulli_2025"` meaning "we looked in gulli for this and didn't find it"), that wins. Otherwise default to `arsanjani_2026` — every `PATTERN_FAILURE_TEMPLATES` entry sources from arsanjani Ch. 7-12 and the rubric IS arsanjani Ch. 12, so book-grounded scenarios are arsanjani-sourced by construction.
- `generate_implementation_plan(consultation_id, output_dir?)` — IMPLEMENTATION PLAN: generate phased markdown checklist from consultation results; classifies steps as "mechanical" (concrete code changes) or "design_decision" (architectural choices); writes markdown to disk, stores plan JSON in DuckDB for cross-session tracking
- `get_implementation_plan(consultation_id)` — GET PLAN: retrieve previously generated plan with progress summary
- `update_plan_step(consultation_id, step_id, status, notes?)` — UPDATE STEP: update step status (pending/in_progress/completed/skipped); recomputes summary, regenerates markdown
- `assert_fact(consultation_id, fact_type, key, value, confidence?, agent_id?, ttl_seconds?)` — BLACKBOARD (assert): append typed, versioned fact (never overwrites); supports confidence scores and TTL
- `query_facts(consultation_id, fact_type?, key?, min_confidence?, detect_conflicts?)` — BLACKBOARD (query): query facts with optional conflict detection and convergence summary
- `rate_consultation(consultation_id, rating?, feedback?)` — QUALITY (rate): record user quality score (1-5) and/or feedback; snapshots consultation metadata
- `consultation_analytics(limit?)` — QUALITY (analytics): surface quality trends across consultations (avg rating, coverage, pattern counts, distribution)
- `render_report(consultation_id, title, executive_brief, system_description, agents, diagram_current, diagram_target, tooltips_current, tooltips_target, recommendation_narratives?, output_dir?)` — RENDER REPORT: server-side HTML report rendering; pulls scores/scenarios/coverage from DB, merges with Claude-provided narrative (~1700 tokens), writes complete HTML with CSS/JS/zoom/tooltips to disk. Phase 5c: provenance badges (`<span class="book-badge">[gulli_2025]</span>` style — subtle gray monospace tags) render next to assessed pattern names in the scorecard and next to scenario titles in the stress-test section. Gated on a single `show_book_badges` flag derived from `score_data["overall_summary"]["by_source_book"]` — present iff at least one assessment carried provenance. Legacy / single-book consultations produce byte-identical HTML to today (the `.book-badge` CSS class always ships in the template, but no `<span>` instances render).

### Prompt
- `consult(context)` — guided architecture consultation; interpolates user's project context into the full 7-step workflow

### Consulting workflow (server instructions)
- Each step narrates progress with visual markers: 💡 aha moments, ✅ celebrations, 🔗 connections, ⚠️ tensions
- Pattern: "This is what I'm doing → this is why → oh! this is what I found."
1. READ PROJECT — read user's codebase first; narrate strengths + early observations
2. MATCH CONCEPTS — `match_concepts` with project description → deterministic concept ranking + `consultation_id`; narrate top matches
2b. PLAN — `plan_consultation` to assess complexity and generate adaptive plan; optionally `supervise_consultation` after each step
3. TRAVERSE GRAPH (scatter-gather) — spawn parallel subagents per seed concept, each calling `get_subgraph` with `consultation_id`; call `log_pattern_assessment` for each pattern found/not yet present/not_applicable; use `write_state`/`read_state` for subagent coordination; use `emit_event` for opportunity discovery
4. RETRIEVE PASSAGES — `ask_book` scoped to discovered concept IDs with `consultation_id`; use `suggested_questions` for follow-ups
5. CHECK COVERAGE + SCORE + RESILIENCE — `consultation_report` to verify coverage; `score_architecture` to get maturity scorecard with current status and goals; `generate_failure_scenarios` to produce concrete resilience scenarios for opportunities
5b. CRITIQUE (optional) — `critique_consultation` for deterministic quality critique; use `prompt_mutations` to address any coverage shortfalls; cap at 1 iteration
6. SYNTHESIZE — call `render_report` with consultation_id and narrative content (title, executive_brief, system_description, agents, diagram_current/target, tooltips_current/target, recommendation_narratives). The tool renders the full HTML report server-side using the reference template and pulls structured data (scores, scenarios, coverage) from the database automatically. Do NOT generate raw HTML — the tool returns the file path
7. OFFER IMPLEMENTATION PLAN — ask user if they want a step-by-step plan; if yes, `generate_implementation_plan`; recommend fresh conversation for implementation using `get_implementation_plan` + `update_plan_step`

## Literature
- Per-book layout: `literature/{book_id}/{book.md, index.md}` (e.g., `literature/arsanjani_2026/`, `literature/gulli_2025/`, `literature/bratanic_2025/`)
- File names + book metadata live in `BOOKS` registry in `config.py`; resolve via `get_book_paths(book_id)`
- Mathpix-extracted LaTeX-flavored markdown (uses `\section*{}` not `#`); index format varies by book
- For `arsanjani_2026` (oracle, mid_level): content starts at line ~985, chapters marked by `\section*{N}` then `\section*{Title}`; index has page numbers
- For `gulli_2025` (implementation): chapters marked by `\section*{Chapter N: Title}`; original index uses *chapter references* (`Concept - Chapter N: Title`) rather than page numbers, so `scripts/synthesize_gulli_index.py` pre-processes it into an Arsanjani-compatible page-numbered shadow index (`INDEX-page-numbered.md`); the synthesized file is what `parse_index.py` consumes
- For `bratanic_2025` (implementation): single Mathpix export split by `scripts/prepare_bratanic_2025.py` (book trimmed to chapters 1-8 at line 3905 — Appendix A/references/marketing excluded; back-of-book index extracted to its own INDEX.md, already page-numbered). Conventional index with lowercase headwords: `index_style: "conventional"` in `BOOKS` makes `parse_index` skip the lowercase sub-entry heuristic (default `"patterns"` preserves arsanjani/gulli behaviour)

## Pipeline
- Every phase script accepts `--book <book_id>` (default `arsanjani_2026`); IDs and queries are book-scoped
- `seed_books_table.py` — seeds the `books` row(s) before any pipeline run; idempotent
- Phase 1a: `parse_index.py` — INDEX.md → concepts table (138 concepts for arsanjani_2026)
- Phase 1b: `parse_book.py` — book → sections table (786 sections, 16 chapters); reads `chapter_boundaries` from `books` table
- Phase 2: `tag_concepts.py` — Claude tags concepts to sections
- Phase 3: `discover_relationships.py` — explicit (Claude) + semantic (embeddings) relationships
- Phase 4: `build_graph.py` — deduplicate, validate, final embeddings (uses section content for embeddings)
- `populate_content.py` — fills `sections.content` from book markdown (run before phase 4 re-embed)
- `extract_indicators.py` — one-time: mines Ch. 12 + source chapters to produce `rubric_data.py` with binary indicators per pattern
- `generate_book_summary.py --book <id> {--draft|--commit|--show}` — Phase 2a: Claude drafts a triage-oriented summary (`--draft` writes to `literature/{book_id}/summary.md`, no DB write), user reviews/edits, then `--commit` embeds it and updates `books.summary` + `books.summary_embedding` via `set_book_summary` (UPDATE, doesn't touch other columns)
- `synthesize_gulli_index.py` — one-shot preprocessor for the `gulli_2025` index (chapter-reference format → Arsanjani-style page-numbered); regenerate by re-running if the upstream INDEX.md changes
- `prepare_bratanic_2025.py` — one-shot: splits the bratanic_2025 Mathpix export into the trimmed book file + INDEX.md (source path via `--src`; anchor sanity-checks fail loudly if the export changes)
- `align_book_pair.py --book-a X --book-b Y` — Phase 3c: cosine-shortlists cross-book concept pairs (top-k per side above threshold), batch-adjudicates un-cached pairs to Claude, persists verdicts to `concept_alignment_cache`. Idempotent: re-runs are no-ops thanks to the cache. `--force` re-adjudicates everything. Reusable by `build_project_kg`
- Orchestrator: `run_pipeline.py --book <id>` — runs all phases for one book; `--reset` clears that book's metadata only

## Notes
- VSS extension loads locally — vector search uses HNSW indexes
- Use `py -m iconsult_mcp.server --check` to test; `py` command for Python on this system
- Scripts use `INSERT OR REPLACE` which DuckDB supports
- When MCP tool output is persisted to disk (too large for inline), do NOT re-read/parse the file with Bash — the data is already in context from the tool call
