# Iconsult MCP: "I make my living as an AI consultant"

**Finally, an AI consultant that actually read the book.**

While other "AI consultants" are busy rephrasing your requirements back to you at $400/hour, Iconsult has ingested an entire textbook on multi-agent architecture, built a knowledge graph of 141 concepts and 462 relationships, and will give you evidence-backed pattern recommendations in under a second. No slide deck. No "circle back." No invoice.

## What It Does

Iconsult is an MCP server that acts as a technical architecture advisor for multi-agent systems. It's backed by a knowledge graph extracted from *Agentic Architectural Patterns for Building Multi-Agent Systems* (Arsanjani & Bustos, Packt 2026) — meaning every recommendation comes with page numbers, not vibes.

### Tools

| Tool | What it does |
|------|-------------|
| `consult` | Describe your architecture problem, get pattern recommendations with provenance |
| `explore_graph` | Browse the knowledge graph — search concepts, find neighbors, trace paths |
| `health_check` | Verify the server is running and the graph is intact |

### The Knowledge Graph

```
141 concepts  ·  786 sections  ·  462 relationships  ·  1,248 concept-section mappings
```

Relationship types span `uses`, `extends`, `alternative_to`, `component_of`, `requires`, `enables`, `complements`, `specializes`, `precedes`, and `conflicts_with` — discovered through five extraction phases including cross-chapter semantic analysis.

## Setup

### Prerequisites

- Python 3.10+
- A [MotherDuck](https://motherduck.com) account (free tier works)
- OpenAI API key (for embeddings)

### Install

```bash
pip install -e .
```

### Environment Variables

```bash
export MOTHERDUCK_TOKEN="your-token"    # Required — database
export OPENAI_API_KEY="sk-..."          # Required — embeddings
export ANTHROPIC_API_KEY="sk-ant-..."   # Required — pipeline extraction only
```

### MCP Configuration

Add to your Claude Desktop or Claude Code config:

```json
{
  "mcpServers": {
    "iconsult": {
      "command": "iconsult-mcp",
      "env": {
        "MOTHERDUCK_TOKEN": "your-token",
        "OPENAI_API_KEY": "sk-..."
      }
    }
  }
}
```

### Verify

```bash
iconsult-mcp --check
```

## Pipeline

The knowledge graph is built in phases from the source book. You don't need to run this unless you're rebuilding from scratch.

```bash
py scripts/run_pipeline.py              # Run all phases
py scripts/run_pipeline.py --phase 3c   # Run a specific sub-phase
py scripts/run_pipeline.py --reset      # Burn it all down and start over
```

| Phase | What it does |
|-------|-------------|
| 1a | Parse book index into concepts |
| 1b | Parse book into sections |
| 2 | Tag concepts to sections (Claude) |
| 3a | Explicit relationships per chapter (Claude) |
| 3b | Semantic similarity pairs (embeddings + Claude) |
| 3c | Cross-chapter knowledge-based relationships (Claude) |
| 3d | Cross-chapter semantic pairs (embeddings + Claude) |
| 3e | Summary-based structural relationships (Claude) |
| 4 | Deduplicate, validate, embed, finalize |

## Architecture

```
src/iconsult_mcp/
  server.py          MCP server entry point
  config.py          Environment + paths
  db.py              DuckDB/MotherDuck connection + schema
  embed.py           OpenAI embeddings + Claude API (raw urllib)
  tools/
    consult.py       Pattern recommendation engine
    explore.py       Graph exploration
    health.py        Health check

scripts/
  run_pipeline.py    Pipeline orchestrator
  parse_index.py     Phase 1a
  parse_book.py      Phase 1b
  tag_concepts.py    Phase 2
  discover_relationships.py   Phases 3a–3e
  build_graph.py     Phase 4
```

DuckDB on MotherDuck for storage. OpenAI `text-embedding-3-small` (1536 dims) for semantic search. Claude for extraction. All HTTP calls go through `urllib` to avoid asyncio deadlocks in the MCP event loop.


## License

MIT
