# Development Guide

## Architecture

```
src/iconsult_mcp/
  server.py          MCP server entry point + consulting playbook
  config.py          Environment + paths
  db.py              DuckDB/MotherDuck connection + schema
  embed.py           OpenAI embeddings + Claude API (raw urllib)
  tools/
    health.py              Health check
    match_concepts.py      Deterministic concept matching (consultation entry point)
    list_concepts.py       Concept catalogue browser
    get_subgraph.py        Graph traversal (BFS) with consultation logging
    ask_book.py            RAG search with suggested questions + consultation logging
    consultation_report.py Coverage metrics + cross-session comparison

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
- 7 tables + 1 metadata table (see `db.py` for schema)
- `sections.content` stores cleaned book text per section (populated by `scripts/populate_content.py`)
- `consultations` table tracks reproducible consultation sessions (fingerprint, matched concepts, step log)
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

## MCP Tools

| Tool | Role | Key behavior |
|------|------|-------------|
| `health_check` | Diagnostics | Server health + graph stats |
| `match_concepts` | **Entry point** | Embeds project description → deterministic concept ranking; creates `consultation_id` + `project_fingerprint` (SHA-256 of normalized text); same input always produces same output |
| `list_concepts` | Browse | Compact catalogue (id, name, category); use `search` to filter by name |
| `get_subgraph` | Query planner | Priority-queue BFS from seed concepts; pass `consultation_id` to log traversal steps (seeds, discovered concepts, relationship types) |
| `ask_book` | Deep context | RAG search over book sections; returns `suggested_questions` derived deterministically from graph edge templates; pass `consultation_id` to log retrieval steps |
| `consultation_report` | Coverage check | Computes concept coverage %, relationship type coverage, passage diversity, prerequisite/conflict checks, gap list; optionally diffs two sessions with same fingerprint |
| `score_architecture` | **Maturity scorecard** | Deterministic scoring from stored `pattern_assessment` steps; computes maturity level (L1-L6), 5 dimension radar scores (Robustness, Coordination, Compliance, User Interaction, Agent Capabilities), gap analysis with severity, recommended metrics from Ch. 7/8/9, implementation roadmap; same consultation always produces same scores |

### Reproducible Consultations

The `match_concepts` → `get_subgraph` → `ask_book` → `consultation_report` pipeline makes consultations reproducible:

1. **Deterministic inputs** — `match_concepts` replaces LLM free-choice concept selection with embedding similarity. Same description → same fingerprint → same concept ranking.
2. **Session tracking** — Every call to `get_subgraph` and `ask_book` with a `consultation_id` logs what was explored (concepts, relationship types, chapters, questions).
3. **Coverage gaps** — `consultation_report` computes what percentage of matched concepts were explored, which relationship types were seen, and flags missing prerequisites/conflicts.
4. **Cross-session comparison** — `consultation_report(id, compare_to=other_id)` diffs two sessions with the same fingerprint to show concept overlap, coverage deltas, and relationship type differences.
5. **Canonical questions** — `ask_book` returns `suggested_questions` generated from graph edge templates (e.g., "What are the prerequisites for X and how does Y fulfill them?"), reducing question formulation variance.
6. **Deterministic scoring** — `score_architecture` reads stored `pattern_assessment` steps and computes maturity level, dimension scores, and gap analysis using fixed formulas. No LLM involved in scoring — same assessments always produce same numbers.

### Consulting Workflow (6 steps)

1. **READ PROJECT** — Read the user's codebase
2. **MATCH CONCEPTS** — `match_concepts` with project description → concept ranking + `consultation_id`
3. **TRAVERSE GRAPH** — `get_subgraph` per seed concept with `consultation_id`; scatter-gather via subagents; log `pattern_assessment` steps for each pattern found/missing in user's code
4. **RETRIEVE PASSAGES** — `ask_book` scoped to discovered concepts with `consultation_id`; follow `suggested_questions`
5. **CHECK COVERAGE + SCORE** — `consultation_report` to verify gaps; `score_architecture` for deterministic maturity scorecard
6. **SYNTHESIZE** — Diagrams, file-level changes, citations, prerequisite/conflict checks, scorecard visualization

## Technical Notes

- VSS extension may not load on MotherDuck; falls back to brute-force cosine similarity
- `py` is the Python command on this system (Windows)
- Use `py -m iconsult_mcp.server --check` for a quick health check
- `iconsult-mcp` entry point defined in `pyproject.toml` under `[project.scripts]`
