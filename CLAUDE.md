# Iconsult MCP

Multi-agent architecture consultant MCP server backed by a knowledge graph extracted from *"Agentic Architectural Patterns for Building Multi-Agent Systems"* (Arsanjani & Bustos, Packt 2026).

## Architecture
- Python MCP server using stdio transport
- DuckDB on MotherDuck for knowledge graph storage
- OpenAI embeddings (text-embedding-3-small, 1536 dims) via raw urllib (no httpx)
- Claude API for extraction tasks via raw urllib
- `src/iconsult_mcp/` layout with hatchling build
- Tools: `tools/health.py`, `tools/list_concepts.py`, `tools/get_subgraph.py`, `tools/ask_book.py`
- Developer docs: `docs/development.md`

## Key Commands
- `pip install -e .` — install in development mode
- `iconsult-mcp` — run MCP server
- `iconsult-mcp --check` — health check
- `py scripts/run_pipeline.py` — run full knowledge graph pipeline

## Environment Variables
- `MOTHERDUCK_TOKEN` — required for database
- `OPENAI_API_KEY` — required for embeddings
- `ANTHROPIC_API_KEY` — required for extraction pipeline

## Database
- MotherDuck database name: `Iconsult` (override with `ICONSULT_DB` env var)
- 6 tables + 1 metadata table (see db.py schema)
- `sections.content` stores cleaned book text per section (populated by `scripts/populate_content.py`)

## MCP Tools
- `health_check` — server health + graph scope
- `list_concepts(search?, include_definitions?)` — ENTRY POINT: compact flat list (id, name, category) by default; `search` filters by name; `include_definitions=true` adds definition text
- `get_subgraph(concept_ids, max_hops=2, confidence_threshold=0.5, max_edges=50, include_descriptions?)` — QUERY PLANNER: priority-queue traversal (highest confidence first); compact edges (from/to/type/confidence); `include_descriptions=true` adds edge descriptions; returns `truncated` flag when edges exceed `max_edges`
- `ask_book(question, concept_ids?, max_passages?)` — DEEP CONTEXT: RAG search; always scope with concept_ids from get_subgraph

### Prompt
- `consult(context)` — guided architecture consultation; interpolates user's project context into the full 5-step workflow

### Consulting workflow (server instructions)
1. READ PROJECT — read user's codebase first
2. MAP TO CONCEPTS — `list_concepts` (compact defaults) to match patterns to concept IDs; use `search` to filter
3. TRAVERSE GRAPH (scatter-gather) — spawn parallel subagents per seed concept, each calling `get_subgraph` with `max_hops=1, include_descriptions=true`; merge summaries. Fallback: call `get_subgraph` directly with compact defaults
4. RETRIEVE PASSAGES — `ask_book` scoped to discovered concept IDs
5. SYNTHESIZE — before/after diagrams via `/generate-web-diagram` skill (HTML+Mermaid; ASCII only for <5 nodes), file-level changes, citations, prerequisite/conflict checks; comparison tables with 4+ rows rendered as HTML

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
