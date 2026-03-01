# Iconsult MCP

Multi-agent architecture consultant MCP server backed by a knowledge graph extracted from *"Agentic Architectural Patterns for Building Multi-Agent Systems"* (Arsanjani & Bustos, Packt 2026).

## Architecture
- Python MCP server using stdio transport
- DuckDB on MotherDuck for knowledge graph storage
- OpenAI embeddings (text-embedding-3-small, 1536 dims) via raw urllib (no httpx)
- Claude API for extraction tasks via raw urllib
- `src/iconsult_mcp/` layout with hatchling build

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
- MotherDuck database name: `iconsult` (override with `ICONSULT_DB` env var)
- 6 tables + 1 metadata table (see db.py schema)
- `sections.content` stores cleaned book text per section (populated by `scripts/populate_content.py`)

## MCP Tools
- `health_check` — server health + graph stats
- `list_concepts` — all 138 concepts grouped by category (browse first)
- `get_subgraph(concept_ids, max_hops, confidence_threshold)` — BFS traversal from seeds
- `ask_book(question, concept_ids?, max_passages?)` — RAG search returning book passages

### Intended flow
1. `list_concepts` → Claude picks relevant concept IDs
2. `get_subgraph` → discover alternatives, prerequisites, related patterns
3. `ask_book` → retrieve actual book text for deep context

Claude owns decomposition, disambiguation, question generation, and synthesis.

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
