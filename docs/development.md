# Development Guide

## Architecture

```
src/iconsult_mcp/
  server.py          MCP server entry point + consulting playbook
  config.py          Environment + paths
  db.py              DuckDB/MotherDuck connection + schema
  embed.py           OpenAI embeddings + Claude API (raw urllib)
  tools/
    health.py        Health check
    list_concepts.py Concept catalogue
    get_subgraph.py  Graph traversal (BFS)
    ask_book.py      RAG search against book sections

scripts/
  run_pipeline.py    Pipeline orchestrator
  parse_index.py     Phase 1a
  parse_book.py      Phase 1b
  populate_content.py  Fill sections.content from book markdown
  tag_concepts.py    Phase 2
  discover_relationships.py   Phases 3a–3e
  build_graph.py     Phase 4

literature/
  Arsanjani and Bustos - 2026 - Agentic architectural patterns...md   Source book
  Arsanjani and Bustos - INDEX.md                                      Book index
```

### Tech Stack

- **Python MCP server** using stdio transport
- **DuckDB on MotherDuck** for knowledge graph storage
- **OpenAI embeddings** (`text-embedding-3-small`, 1536 dims) for semantic search
- **Claude API** for extraction tasks during pipeline
- **All HTTP via raw `urllib`** — avoids asyncio deadlocks in the MCP event loop (no httpx)
- **Hatchling** build system

## Database

- MotherDuck database name: `iconsult` (override with `ICONSULT_DB` env var)
- 6 tables + 1 metadata table (see `db.py` for schema)
- `sections.content` stores cleaned book text per section (populated by `scripts/populate_content.py`)
- Scripts use `INSERT OR REPLACE` which DuckDB supports

## Pipeline

The knowledge graph is built in phases from the source book. You only need to run this if rebuilding from scratch.

### Environment Variables (pipeline only)

```bash
export MOTHERDUCK_TOKEN="your-token"    # Required — database
export OPENAI_API_KEY="sk-..."          # Required — embeddings
export ANTHROPIC_API_KEY="sk-ant-..."   # Required — Claude extraction
```

### Commands

```bash
py scripts/run_pipeline.py              # Run all phases
py scripts/run_pipeline.py --phase 3c   # Run a specific sub-phase
py scripts/run_pipeline.py --reset      # Clear everything and start over
```

### Phases

| Phase | Script | What it does |
|-------|--------|-------------|
| 1a | `parse_index.py` | Parse book index → concepts table (138 concepts) |
| 1b | `parse_book.py` | Parse book → sections table (786 sections, 16 chapters) |
| — | `populate_content.py` | Fill `sections.content` from book markdown (run before phase 4 re-embed) |
| 2 | `tag_concepts.py` | Claude tags concepts to sections |
| 3a | `discover_relationships.py` | Explicit relationships per chapter (Claude) |
| 3b | `discover_relationships.py` | Semantic similarity pairs (embeddings + Claude) |
| 3c | `discover_relationships.py` | Cross-chapter knowledge-based relationships (Claude) |
| 3d | `discover_relationships.py` | Cross-chapter semantic pairs (embeddings + Claude) |
| 3e | `discover_relationships.py` | Summary-based structural relationships (Claude) |
| 4 | `build_graph.py` | Deduplicate, validate, embed, finalize |

## Literature Files

- Both files are Mathpix-extracted LaTeX-flavored markdown (uses `\section*{}` not `#`)
- Book content starts at line ~985 (Part 1); chapters marked by `\section*{N}` then `\section*{Title}`
- Index has OCR artifacts: merged page numbers, separated name/number blocks

## Technical Notes

- VSS extension may not load on MotherDuck; falls back to brute-force cosine similarity
- `py` is the Python command on this system (Windows)
- Use `py -m iconsult_mcp.server --check` for a quick health check
- `iconsult-mcp` entry point defined in `pyproject.toml` under `[project.scripts]`
