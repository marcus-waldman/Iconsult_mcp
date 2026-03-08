# Iconsult MCP

Multi-agent architecture consultant MCP server backed by a knowledge graph extracted from *"Agentic Architectural Patterns for Building Multi-Agent Systems"* (Arsanjani & Bustos, Packt 2026).

## Architecture
- Python MCP server using stdio transport
- DuckDB on MotherDuck for knowledge graph storage
- OpenAI embeddings (text-embedding-3-small, 1536 dims) via raw urllib (no httpx)
- Claude API for extraction tasks via raw urllib
- `src/iconsult_mcp/` layout with hatchling build
- Tools: `tools/health.py`, `tools/match_concepts.py`, `tools/list_concepts.py`, `tools/get_subgraph.py`, `tools/ask_book.py`, `tools/consultation_report.py`, `tools/score_architecture.py`, `tools/log_pattern_assessment.py`
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
- Tests: `test_match_concepts.py` (concept matching quality), `test_subgraph.py` (graph traversal), `test_score_architecture.py` (scoring), `test_consultation_flow.py` (end-to-end)

## Environment Variables
- `MOTHERDUCK_TOKEN` — required for database
- `OPENAI_API_KEY` — required for embeddings
- `ANTHROPIC_API_KEY` — required for extraction pipeline

## Database
- MotherDuck database name: `Iconsult` (override with `ICONSULT_DB` env var)
- 7 tables + 1 metadata table (see db.py schema); `consultations` table tracks reproducible sessions
- `sections.content` stores cleaned book text per section (populated by `scripts/populate_content.py`)

## MCP Tools
- `health_check` — server health + graph scope
- `match_concepts(project_description, max_results?, similarity_threshold?)` — ENTRY POINT: deterministic embedding match; creates `consultation_id` for session tracking; same description → same ranking
- `list_concepts(search?, include_definitions?)` — BROWSE: compact flat list (id, name, category); use for catalogue browsing, not as consultation entry point
- `get_subgraph(concept_ids, max_hops=2, confidence_threshold=0.5, max_edges=50, include_descriptions?, consultation_id?)` — QUERY PLANNER: priority-queue traversal; logs steps when `consultation_id` provided
- `ask_book(question, concept_ids?, max_passages?, consultation_id?)` — DEEP CONTEXT: RAG search; returns `suggested_questions` from graph edges; logs steps when `consultation_id` provided
- `consultation_report(consultation_id, compare_to?)` — COVERAGE CHECK: concept/relationship coverage %, passage diversity, gap identification, cross-session diff
- `log_pattern_assessment(consultation_id, pattern_id, pattern_name, status, evidence?, maturity_level?)` — LOG ASSESSMENT: record a pattern assessment during graph traversal; status is "implemented", "partial", "missing", or "not_applicable" (pattern irrelevant to this architecture); these feed into `score_architecture`
- `score_architecture(consultation_id, target_level?, roadmap_levels?)` — MATURITY SCORECARD: deterministic scoring from stored `pattern_assessment` steps; computes maturity level (L1-L6), pattern status with phase-aligned goals, gap analysis with severity, recommended metrics, implementation roadmap. `roadmap_levels` (default 3) controls how many levels the roadmap/goals cover. Each pattern gets a `phase` field (1-based) tying it to its implementation phase.

### Prompt
- `consult(context)` — guided architecture consultation; interpolates user's project context into the full 6-step workflow

### Consulting workflow (server instructions)
1. READ PROJECT — read user's codebase first
2. MATCH CONCEPTS — `match_concepts` with project description → deterministic concept ranking + `consultation_id`
3. TRAVERSE GRAPH (scatter-gather) — spawn parallel subagents per seed concept, each calling `get_subgraph` with `consultation_id`; call `log_pattern_assessment` for each pattern found/missing/not_applicable in user's code; use "not_applicable" for patterns irrelevant to the architecture (e.g., Agent Calls Human for batch pipelines); merge summaries
4. RETRIEVE PASSAGES — `ask_book` scoped to discovered concept IDs with `consultation_id`; use `suggested_questions` for follow-ups
5. CHECK COVERAGE + SCORE — `consultation_report` to verify coverage; `score_architecture` to get maturity scorecard with current status and goals
6. SYNTHESIZE — render entire consultation as a single HTML page via `/generate-web-diagram` skill (ASCII only for <5 nodes). HTML must include in order: (a) Executive Brief callout (3-4 sentences for decision makers), (b) Maturity banner (current → target level), (c) System Under Review (architecture, agent roster with tools), (d) Maturity Scorecard table with hover tooltips on every pattern (definition + context-sensitive detail: how implemented / what's missing and why it matters + book ref), (e) Before/After Mermaid diagrams (red gaps / green additions), (f) Implementation Recommendations cards by phase with code snippets + citations, (g) Failure Recovery Chain. Also check prerequisite/conflict edges; render comparison tables as HTML when 4+ rows

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
