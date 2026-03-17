# Iconsult MCP

Multi-agent architecture consultant MCP server backed by a knowledge graph extracted from *"Agentic Architectural Patterns for Building Multi-Agent Systems"* (Arsanjani & Bustos, Packt 2026).

## Architecture
- Python MCP server using stdio transport
- DuckDB on MotherDuck for knowledge graph storage
- OpenAI embeddings (text-embedding-3-small, 1536 dims) via raw urllib (no httpx)
- Claude API for extraction tasks via raw urllib
- `src/iconsult_mcp/` layout with hatchling build
- Tools: `tools/health.py`, `tools/match_concepts.py`, `tools/list_concepts.py`, `tools/get_subgraph.py`, `tools/ask_book.py`, `tools/consultation_report.py`, `tools/score_architecture.py`, `tools/log_pattern_assessment.py`, `tools/validate_subagent.py`, `tools/critique_consultation.py`, `tools/shared_state.py`, `tools/events.py`, `tools/plan_consultation.py`, `tools/supervise_consultation.py`, `tools/failure_scenarios.py`, `tools/implementation_plan.py`, `tools/blackboard.py`, `tools/quality.py`
- L4 modules: `access_policy.py` (tool access levels + consultation ownership validation)
- Pattern ID aliasing: `_PATTERN_ID_ALIASES` in `score_architecture.py` bridges MATURITY_MODEL IDs ↔ KG concept IDs; `normalize_pattern_id()` resolves either to canonical form
- Resilience: `escalation.py` (structured error responses), dispatch dict + timeout/retry in `server.py`
- Developer docs: `docs/development.md`

## Key Commands
- `pip install -e .` — install in development mode
- `iconsult-mcp` — run MCP server
- `iconsult-mcp --check` — health check
- `py scripts/run_pipeline.py` — run full knowledge graph pipeline
- `py -m pytest tests/ -v` — run integration tests (requires MOTHERDUCK_TOKEN + OPENAI_API_KEY)
- `py -m pytest tests/test_match_concepts.py -v` — run concept matching tests only

## Testing
- Integration tests in `tests/` — require MOTHERDUCK_TOKEN and OPENAI_API_KEY env vars
- Test cases in `tests/cases.py` — 12 architectures derived from openai/openai-agents-python examples
- Adding a test case = adding a dict to `CASES` in `tests/cases.py` (id, description, expected_concepts, pattern_assessments)
- Tests: `test_match_concepts.py` (concept matching quality), `test_subgraph.py` (graph traversal), `test_score_architecture.py` (scoring), `test_failure_scenarios.py` (stress test demos), `test_implementation_plan.py` (plan generation/tracking), `test_consultation_flow.py` (end-to-end), `test_pattern_id_aliases.py` (pattern ID alias resolution), `test_blackboard.py` (blackboard knowledge hub)

## Environment Variables
- `MOTHERDUCK_TOKEN` — required for database
- `OPENAI_API_KEY` — required for embeddings
- `ANTHROPIC_API_KEY` — required for extraction pipeline

## Config (config.py)
- `TOOL_TIMEOUT_SECONDS` = 30 — default timeout for tool calls
- `TOOL_MAX_RETRIES` = 2 — max retries for retryable tools (ConnectionError, TimeoutError, OSError)
- `TOOL_RETRY_BASE_DELAY` = 1.0 — base delay for exponential backoff (delay = base × 2^attempt)

## Database
- MotherDuck database name: `Iconsult` (override with `ICONSULT_DB` env var)
- 12 tables + 1 metadata table (see db.py schema); `consultations` table tracks reproducible sessions; `consultation_state` for shared epistemic memory; `consultation_events` for event-driven reactivity; `implementation_plans` for cross-session plan persistence; `blackboard_facts` for typed, versioned scatter-gather coordination; `consultation_quality` for quality ratings and feedback
- `sections.content` stores cleaned book text per section (populated by `scripts/populate_content.py`)

## MCP Tools
- `health_check` — server health + graph scope
- `match_concepts(project_description, max_results?, similarity_threshold?)` — ENTRY POINT: deterministic embedding match; creates `consultation_id` for session tracking; same description → same ranking
- `list_concepts(search?, include_definitions?)` — BROWSE: compact flat list (id, name, category); use for catalogue browsing, not as consultation entry point
- `get_subgraph(concept_ids, max_hops=2, confidence_threshold=0.5, max_edges=50, include_descriptions?, consultation_id?)` — QUERY PLANNER: priority-queue traversal; logs steps when `consultation_id` provided
- `ask_book(question, concept_ids?, max_passages?, consultation_id?)` — DEEP CONTEXT: RAG search; returns `suggested_questions` from graph edges; logs steps when `consultation_id` provided
- `consultation_report(consultation_id, compare_to?)` — COVERAGE CHECK: concept coverage (matched concepts that were traversed OR assessed), relationship type coverage, passage diversity, gap identification, cross-session diff
- `log_pattern_assessment(consultation_id, pattern_id, pattern_name, status, evidence?, maturity_level?, failure_context?)` — LOG ASSESSMENT: record a pattern assessment during graph traversal; status is "implemented", "partial", "missing", or "not_applicable" (pattern irrelevant to this architecture); optional `failure_context` (dict with `code_refs`, `failure_mode`, `depends_on`) captures structured evidence for stress test demos; these feed into `score_architecture` and `generate_failure_scenarios`
- `score_architecture(consultation_id, target_level?, roadmap_levels?)` — MATURITY SCORECARD: deterministic scoring from stored `pattern_assessment` steps; computes maturity level (L1-L6), pattern status with phase-aligned goals, gap analysis with severity, recommended metrics, implementation roadmap. `roadmap_levels` (default 3) controls how many levels the roadmap/goals cover. Each pattern gets a `phase` field (1-based) tying it to its implementation phase.
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

### Prompt
- `consult(context)` — guided architecture consultation; interpolates user's project context into the full 7-step workflow

### Consulting workflow (server instructions)
1. READ PROJECT — read user's codebase first
2. MATCH CONCEPTS — `match_concepts` with project description → deterministic concept ranking + `consultation_id`
2b. PLAN — `plan_consultation` to assess complexity and generate adaptive plan; optionally `supervise_consultation` after each step
3. TRAVERSE GRAPH (scatter-gather) — spawn parallel subagents per seed concept, each calling `get_subgraph` with `consultation_id`; call `log_pattern_assessment` for each pattern found/not yet present/not_applicable; use `write_state`/`read_state` for subagent coordination; use `emit_event` for opportunity discovery
4. RETRIEVE PASSAGES — `ask_book` scoped to discovered concept IDs with `consultation_id`; use `suggested_questions` for follow-ups
5. CHECK COVERAGE + SCORE + RESILIENCE — `consultation_report` to verify coverage; `score_architecture` to get maturity scorecard with current status and goals; `generate_failure_scenarios` to produce concrete resilience scenarios for opportunities
5b. CRITIQUE (optional) — `critique_consultation` for deterministic quality critique; use `prompt_mutations` to address any coverage shortfalls; cap at 1 iteration
6. SYNTHESIZE — render entire consultation as a single HTML page via `/generate-web-diagram` skill (ASCII only for <5 nodes). HTML must include in order: (a) Executive Brief callout (what system does well + most impactful opportunity, for decision makers), (b) Maturity banner (current → target level), (c) System Under Review (architecture, agent roster with tools), (d) Maturity Scorecard table with hover tooltips on every pattern (definition + context-sensitive detail: how implemented / what's the opportunity and why it matters + book ref), (e) Before/After Mermaid diagrams with interactive hover tooltips on every node (role, responsibilities, why it matters; current: what it does today, target: what changes/additions), (f) Implementation Recommendations cards by phase with code snippets + citations, (g) Failure Recovery Chain, (h) Resilience Scenarios (collapsible scenario traces with code refs, book citations, foundation dependency notes, Ch. 7 recovery chain coverage). Also check prerequisite/conflict edges; render comparison tables as HTML when 4+ rows
7. OFFER IMPLEMENTATION PLAN — ask user if they want a step-by-step plan; if yes, `generate_implementation_plan`; recommend fresh conversation for implementation using `get_implementation_plan` + `update_plan_step`

## Literature
- Book markdown: `literature/Arsanjani and Bustos - 2026 - ....md`
- Index markdown: `literature/Arsanjani and Bustos - INDEX.md`
- Both are Mathpix-extracted LaTeX-flavored markdown (uses `\section*{}` not `#`)
- Content starts at line ~985 (Part 1); chapters marked by `\section*{N}` then `\section*{Title}`
- Index has OCR artifacts: merged page numbers, separated name/number blocks

## Pipeline
- Phase 1a: `parse_index.py` — INDEX.md → concepts table (138 concepts)
- Phase 1b: `parse_book.py` — book → sections table (786 sections, 16 chapters)
- Phase 2: `tag_concepts.py` — Claude tags concepts to sections
- Phase 3: `discover_relationships.py` — explicit (Claude) + semantic (embeddings) relationships
- Phase 4: `build_graph.py` — deduplicate, validate, final embeddings (uses section content for embeddings)
- `populate_content.py` — fills `sections.content` from book markdown (run before phase 4 re-embed)
- Orchestrator: `run_pipeline.py` — runs all phases, `--phase 1a` for single phase, `--reset` to clear

## Notes
- VSS extension may not load on MotherDuck; falls back to brute-force cosine similarity
- Use `py -m iconsult_mcp.server --check` to test; `py` command for Python on this system
- Scripts use `INSERT OR REPLACE` which DuckDB supports
- When MCP tool output is persisted to disk (too large for inline), do NOT re-read/parse the file with Bash — the data is already in context from the tool call
