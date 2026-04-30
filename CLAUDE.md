# Iconsult MCP

Multi-agent architecture consultant MCP server backed by a knowledge graph extracted from *"Agentic Architectural Patterns for Building Multi-Agent Systems"* (Arsanjani & Bustos, Packt 2026).

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

## Testing
- Integration tests in `tests/` — require OPENAI_API_KEY and ANTHROPIC_API_KEY env vars
- Test cases in `tests/cases.py` — 12 architectures derived from openai/openai-agents-python examples
- Adding a test case = adding a dict to `CASES` in `tests/cases.py` (id, description, expected_concepts, pattern_assessments)
- Tests: `test_match_concepts.py` (concept matching quality), `test_subgraph.py` (graph traversal), `test_score_architecture.py` (scoring), `test_failure_scenarios.py` (stress test demos), `test_implementation_plan.py` (plan generation/tracking), `test_consultation_flow.py` (end-to-end), `test_pattern_id_aliases.py` (pattern ID alias resolution), `test_blackboard.py` (blackboard knowledge hub), `test_step_buffer.py` (write-behind buffer), `test_triage.py` (book triage tool), `test_projects_schema.py` (Phase 3a projects + canonical_concepts + concept_alignment_cache schema and helpers)

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
- Concept and section IDs are `{book_id}__{slug}` namespaced; `normalize_pattern_id()` strips the prefix before alias lookup so the rubric stays book-agnostic
- `consultations` tracks reproducible sessions; `consultation_state` shared memory; `consultation_events` reactivity; `implementation_plans` cross-session plans; `blackboard_facts` typed/versioned coordination; `consultation_quality` ratings
- `sections.content` stores cleaned book text per section (populated by `scripts/populate_content.py`)

## MCP Tools
- `health_check` — server health + graph scope
- `match_concepts(project_description, max_results?, similarity_threshold?)` — ENTRY POINT: deterministic embedding match; creates `consultation_id` for session tracking; same description → same ranking
- `triage_books(project_description, top_k=5, threshold=0.4)` — TRIAGE: deterministic cosine match against `books.summary_embedding`; ranks registered books by relevance to a project description; pure read tool, no consultation_id created; degenerate while only one book is registered
- `list_books(altitude?)` — BROWSE: list registered books in the corpus catalogue with optional altitude filter; pure read tool
- `list_concepts(search?, include_definitions?)` — BROWSE: compact flat list (id, name, category); use for catalogue browsing, not as consultation entry point
- `get_subgraph(concept_ids, max_hops=2, confidence_threshold=0.5, max_edges=50, include_descriptions?, consultation_id?)` — QUERY PLANNER: priority-queue traversal; logs steps when `consultation_id` provided
- `ask_book(question, concept_ids?, max_passages?, consultation_id?)` — DEEP CONTEXT: RAG search; returns `suggested_questions` from graph edges; logs steps when `consultation_id` provided
- `consultation_report(consultation_id, compare_to?)` — COVERAGE CHECK: concept coverage (matched concepts that were traversed OR assessed), relationship type coverage, passage diversity, gap identification, cross-session diff
- `log_pattern_assessment(consultation_id, pattern_id, pattern_name, status, evidence?, maturity_level?, failure_context?, category?, indicators?)` — LOG ASSESSMENT: record a pattern assessment during graph traversal; status is "implemented", "partial", "missing", or "not_applicable"; when `indicators` provided (list of `{text, met, na?}`), status auto-computed from indicators; `category` auto-resolved from rubric; optional `failure_context` for stress test demos
- `score_architecture(consultation_id)` — CATEGORY-BASED RUBRIC: deterministic scoring from stored `pattern_assessment` steps; 7 categories (Coordination, Explainability, Robustness, Human-Agent, Agent Capabilities, Infrastructure, Continuous Improvement) × 3 levels (Basic/Intermediate/Advanced) from Ch. 12; each category rated Not Started/Emerging/Established/Mature; binary indicators per pattern; gap analysis with missing indicators; roadmap by category (weakest first)
- `validate_subagent(response, validate_against_graph?)` — VALIDATE: schema validation for subagent JSON responses {concept, key_relationships, recommendation, discovered_ids}; pure structural checks, no LLM; optional `validate_against_graph` verifies discovered_ids exist in concepts table and concept matches a known name (returns semantic_warnings separately)
- `critique_consultation(consultation_id, max_iterations?)` — CRITIQUE: deterministic quality critique of consultation steps; checks workflow completeness, traversal depth, assessment coverage, passage diversity, critical edges; returns issues with severity + `prompt_mutations` for adaptive retry; `max_iterations` (1-3) enables multi-pass critique with convergence/stuck-loop detection
- `write_state(consultation_id, key, value)` — SHARED STATE (write): upsert key-value pair for subagent coordination; logs state_write step
- `read_state(consultation_id, key?)` — SHARED STATE (read): read one key or all entries from shared state
- `emit_event(consultation_id, event_type, data?)` — EVENT (emit): emit consultation event (gap_found, pattern_assessed, coverage_threshold_reached, coverage_dropped, plan_created, state_conflict); returns reactive suggestion
- `get_events(consultation_id, since_id?, event_type?)` — EVENT (poll): poll events with optional filters
- `plan_consultation(consultation_id)` — PLAN: assess complexity (simple/moderate/complex) and generate adaptive step-by-step plan after match_concepts
- `supervise_consultation(consultation_id)` — SUPERVISE: track workflow progress (phases completed/remaining, percent), suggest next action with tool + params, include event alerts and shared state
- `generate_failure_scenarios(consultation_id, max_scenarios?)` — RESILIENCE ANALYSIS: deterministic resilience scenario walkthroughs for patterns not yet in place; each scenario illustrates how the architecture responds under stress (trigger → propagation steps with file:line refs when code available → potential impact); maps Ch. 7 five-step failure chain; notes foundation dependencies when advanced patterns rely on patterns not yet implemented; two modes: code-grounded (from `failure_context.code_refs`) or book-grounded (from pattern scenario templates)
- `generate_implementation_plan(consultation_id, output_dir?)` — IMPLEMENTATION PLAN: generate phased markdown checklist from consultation results; classifies steps as "mechanical" (concrete code changes) or "design_decision" (architectural choices); writes markdown to disk, stores plan JSON in DuckDB for cross-session tracking
- `get_implementation_plan(consultation_id)` — GET PLAN: retrieve previously generated plan with progress summary
- `update_plan_step(consultation_id, step_id, status, notes?)` — UPDATE STEP: update step status (pending/in_progress/completed/skipped); recomputes summary, regenerates markdown
- `assert_fact(consultation_id, fact_type, key, value, confidence?, agent_id?, ttl_seconds?)` — BLACKBOARD (assert): append typed, versioned fact (never overwrites); supports confidence scores and TTL
- `query_facts(consultation_id, fact_type?, key?, min_confidence?, detect_conflicts?)` — BLACKBOARD (query): query facts with optional conflict detection and convergence summary
- `rate_consultation(consultation_id, rating?, feedback?)` — QUALITY (rate): record user quality score (1-5) and/or feedback; snapshots consultation metadata
- `consultation_analytics(limit?)` — QUALITY (analytics): surface quality trends across consultations (avg rating, coverage, pattern counts, distribution)
- `render_report(consultation_id, title, executive_brief, system_description, agents, diagram_current, diagram_target, tooltips_current, tooltips_target, recommendation_narratives?, output_dir?)` — RENDER REPORT: server-side HTML report rendering; pulls scores/scenarios/coverage from DB, merges with Claude-provided narrative (~1700 tokens), writes complete HTML with CSS/JS/zoom/tooltips to disk

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
- Per-book layout: `literature/{book_id}/{book.md, index.md}` (e.g., `literature/arsanjani_2026/`)
- File names + book metadata live in `BOOKS` registry in `config.py`; resolve via `get_book_paths(book_id)`
- Mathpix-extracted LaTeX-flavored markdown (uses `\section*{}` not `#`); index has OCR artifacts (merged page numbers, separated name/number blocks)
- For arsanjani_2026: content starts at line ~985, chapters marked by `\section*{N}` then `\section*{Title}`

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
- Orchestrator: `run_pipeline.py --book <id>` — runs all phases for one book; `--reset` clears that book's metadata only

## Notes
- VSS extension loads locally — vector search uses HNSW indexes
- Use `py -m iconsult_mcp.server --check` to test; `py` command for Python on this system
- Scripts use `INSERT OR REPLACE` which DuckDB supports
- When MCP tool output is persisted to disk (too large for inline), do NOT re-read/parse the file with Bash — the data is already in context from the tool call
