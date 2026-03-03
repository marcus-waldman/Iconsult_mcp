"""
MCP server entry point for iconsult-mcp.

Provides architecture consultation tools backed by a knowledge graph
extracted from "Agentic Architectural Patterns for Building Multi-Agent Systems".
"""

import asyncio
import json
import logging
import sys
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import GetPromptResult, Prompt, PromptArgument, PromptMessage, TextContent, Tool

from iconsult_mcp.tools.health import health_check
from iconsult_mcp.tools.list_concepts import list_concepts
from iconsult_mcp.tools.get_subgraph import get_subgraph
from iconsult_mcp.tools.ask_book import ask_book

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

INSTRUCTIONS = """\
You are an architecture consultant specializing in multi-agent systems. You have \
access to a knowledge graph extracted from "Agentic Architectural Patterns for \
Building Multi-Agent Systems" (Arsanjani & Bustos, Packt 2026) containing 138 \
concepts, their relationships, and full book text.

## Consulting Workflow

1. **READ PROJECT** — Always read the user's codebase first. Understand their \
current architecture, tech stack, and pain points before consulting the graph. \
Then narrate in 1-2 sentences: what you found and what the core problem is.

2. **MAP TO CONCEPTS** — Call `list_concepts` to browse the full catalogue. Match \
what you see in the user's code to concept IDs (patterns, frameworks, components \
they already use or should consider). \
Then narrate in 1-2 sentences: which concepts matched and why they fit.

3. **TRAVERSE GRAPH** — Call `get_subgraph` with matched concept IDs. The graph is \
your query planner. Use relationship types to reason about fit:
   - `uses` / `component_of` — what the pattern includes
   - `extends` / `specializes` — more specific variants
   - `alternative_to` — competing approaches to compare
   - `requires` / `precedes` / `enables` — prerequisites and sequencing
   - `conflicts_with` — incompatibilities to flag
   - `complements` — patterns that work well together
   Then narrate in 1-2 sentences: the single most significant finding — a missing \
prerequisite, a conflict, or an alternative worth considering.

4. **RETRIEVE PASSAGES** — Call `ask_book` scoped to concept IDs discovered in \
step 3. This retrieves actual book text with chapter/page citations. \
Then narrate in 1-2 sentences: the key insight the book provides.

5. **SYNTHESIZE** — Deliver project-specific recommendations:
   - Ground every recommendation in the user's specific files and code
   - Render before/after architecture diagrams using the `/generate-web-diagram` skill \
(writes a self-contained HTML file with Mermaid; opens in browser). Only fall back to \
ASCII if the diagram has fewer than ~5 nodes and no edge labels.
   - Cite book passages with chapter and page numbers
   - Check `requires` edges — flag missing prerequisites
   - Check `conflicts_with` edges — warn about incompatibilities
   - Compare alternatives using `alternative_to` edges with pros/cons. For comparisons \
with 4+ rows or 3+ columns, use `/generate-web-diagram` to render as a styled HTML table.

## Rules
- Never recommend patterns without first checking prerequisites and conflicts.
- Always show how recommendations map onto the user's actual codebase.
- When multiple alternatives exist, present a comparison table before recommending.
- Cite the book: include chapter number, page number, and a brief quote when relevant.
"""

server = Server("iconsult-mcp", instructions=INSTRUCTIONS)


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List all available tools."""
    return [
        Tool(
            name="health_check",
            description=(
                "Check server health and graph scope. Returns database connection status, "
                "graph statistics (concept count, relationship count, avg confidence), "
                "and pipeline status. Call this first to understand how large the knowledge "
                "graph is and whether the database is reachable."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="list_concepts",
            description=(
                "ENTRY POINT — List all 138 concepts in the knowledge graph, grouped by "
                "category. Returns concept IDs, names, and definitions. Call this after "
                "reading the user's codebase to map their existing patterns and components "
                "to concept IDs. These IDs are required input for get_subgraph and ask_book."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="get_subgraph",
            description=(
                "QUERY PLANNER — Bounded graph traversal from seed concepts. Given one or "
                "more concept IDs (from list_concepts), performs BFS up to max_hops and "
                "returns all reachable nodes and edges. Use relationship types to discover "
                "what the user is missing: alternative_to for competing approaches, requires "
                "for prerequisites, conflicts_with for incompatibilities, complements for "
                "synergies. Feed discovered concept IDs into ask_book for supporting text."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "concept_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of concept IDs to start traversal from",
                    },
                    "max_hops": {
                        "type": "integer",
                        "description": "Maximum traversal depth (1-3, default: 2)",
                    },
                    "confidence_threshold": {
                        "type": "number",
                        "description": "Minimum edge confidence to traverse (0.0-1.0, default: 0.0)",
                    },
                },
                "required": ["concept_ids"],
            },
        ),
        Tool(
            name="ask_book",
            description=(
                "DEEP CONTEXT — RAG search against book sections. Embeds a natural language "
                "question and returns the most relevant book passages with full text, chapter, "
                "page numbers, and section title. ALWAYS scope with concept_ids from "
                "get_subgraph for precision — unscoped queries search the entire book and "
                "may return less relevant results."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Natural language question to search for in the book",
                    },
                    "concept_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional: scope search to sections linked to these concept IDs",
                    },
                    "max_passages": {
                        "type": "integer",
                        "description": "Maximum number of passages to return (default: 3)",
                    },
                },
                "required": ["question"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls."""

    if name == "health_check":
        result = await health_check()
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "list_concepts":
        result = await list_concepts()
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "get_subgraph":
        result = await get_subgraph(
            concept_ids=arguments.get("concept_ids", []),
            max_hops=arguments.get("max_hops", 2),
            confidence_threshold=arguments.get("confidence_threshold", 0.0),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "ask_book":
        result = await ask_book(
            question=arguments.get("question", ""),
            concept_ids=arguments.get("concept_ids"),
            max_passages=arguments.get("max_passages", 3),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


@server.list_prompts()
async def list_prompts() -> list[Prompt]:
    """List available prompts."""
    return [
        Prompt(
            name="consult",
            description=(
                "Start an architecture consultation. Provide your project context "
                "and get expert multi-agent system design advice grounded in the book."
            ),
            arguments=[
                PromptArgument(
                    name="context",
                    description=(
                        "Describe your project: tech stack, current architecture, "
                        "what you're trying to achieve, and any pain points."
                    ),
                    required=True,
                ),
            ],
        ),
    ]


@server.get_prompt()
async def get_prompt(name: str, arguments: dict[str, str] | None) -> GetPromptResult:
    """Handle prompt requests."""
    if name != "consult":
        raise ValueError(f"Unknown prompt: {name}")

    context = (arguments or {}).get("context", "No project context provided.")

    return GetPromptResult(
        description="Architecture consultation workflow",
        messages=[
            PromptMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text=f"""\
I need architecture consulting for my project. Here is my context:

{context}

Please follow this workflow:

1. **Read my codebase** — Examine my project files to understand the current \
architecture, tech stack, and patterns in use. Then tell me in 1-2 sentences \
what you found and what you see as the core problem.

2. **Map to concepts** — Call `list_concepts` to browse the knowledge graph \
catalogue. Identify which concepts match patterns I already use and which ones \
might address my needs. Then tell me in 1-2 sentences which concepts matched.

3. **Traverse the graph** — Call `get_subgraph` with the matched concept IDs. \
Use the relationship types (alternative_to, requires, conflicts_with, complements, \
enables, extends) to discover related patterns and reason about fit. Then tell me \
in 1-2 sentences the single most significant finding from the graph.

4. **Retrieve book passages** — Call `ask_book` scoped to the discovered concept \
IDs for authoritative guidance. Cite chapter and page numbers. Then tell me in \
1-2 sentences the key insight the book provides.

5. **Synthesize recommendations** — Deliver:
   - Before/after architecture diagrams rendered with `/generate-web-diagram` (HTML + \
Mermaid, opens in browser). Use ASCII only for trivial diagrams with fewer than ~5 nodes.
   - Specific file-level changes mapped to my codebase
   - Prerequisites check (requires edges) and conflict warnings (conflicts_with edges)
   - Comparison of alternatives if multiple approaches exist — render as HTML table via \
`/generate-web-diagram` when the table has 4+ rows or 3+ columns
   - Book citations with chapter, page, and brief quotes""",
                ),
            ),
        ],
    )


async def run_server():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def _print_startup_diagnostics():
    """Print startup diagnostics to stderr."""
    import os

    critical = {"MOTHERDUCK_TOKEN": "Required for database"}
    optional = {"OPENAI_API_KEY": "Required for embeddings"}

    missing_critical = [f"  - {k}: {v}" for k, v in critical.items() if not os.environ.get(k)]
    missing_optional = [f"  - {k}: {v}" for k, v in optional.items() if not os.environ.get(k)]

    if missing_critical:
        print("iconsult-mcp: WARNING - Missing critical environment variables:", file=sys.stderr)
        for line in missing_critical:
            print(line, file=sys.stderr)

    if missing_optional:
        print(f"iconsult-mcp: Optional env vars not set:", file=sys.stderr)
        for line in missing_optional:
            print(line, file=sys.stderr)


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="iconsult-mcp",
        description="MCP server for multi-agent architecture consultation",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run health check and exit",
    )
    args = parser.parse_args()

    if args.check:
        result = asyncio.run(health_check())
        print(json.dumps(result, indent=2))
        sys.exit(0 if result.get("status") == "healthy" else 1)

    _print_startup_diagnostics()
    asyncio.run(run_server())


if __name__ == "__main__":
    main()
