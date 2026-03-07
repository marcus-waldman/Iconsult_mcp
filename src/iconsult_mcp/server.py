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
from iconsult_mcp.tools.match_concepts import match_concepts
from iconsult_mcp.tools.consultation_report import consultation_report

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

2. **MATCH CONCEPTS** — Call `match_concepts` with a concise project description. \
This deterministically embeds the description and returns ranked concept matches with \
a `consultation_id` that tracks the session. The same description always produces the \
same concept ranking. Use `list_concepts` only for browsing/filtering the full catalogue.

3. **TRAVERSE GRAPH (scatter-gather)** — For each matched seed concept, spawn a \
parallel subagent (via the Agent tool) to explore its neighbourhood independently. \
Each subagent should use this prompt template:

   ```
   You are a graph analysis subagent. Given this architectural context:
   {architectural_summary}
   Explore concept "{concept_name}" (ID: {concept_id}).
   Call get_subgraph(concept_ids=["{concept_id}"], max_hops=1, include_descriptions=true, consultation_id="{consultation_id}").
   Analyze relationships using these types:
   - uses / component_of — what the pattern includes
   - extends / specializes — more specific variants
   - alternative_to — competing approaches to compare
   - requires / precedes / enables — prerequisites and sequencing
   - conflicts_with — incompatibilities to flag
   - complements — patterns that work well together
   Return a JSON object with: concept, key_relationships, recommendation, discovered_ids.
   Keep response under 300 tokens.
   ```

   Pass `consultation_id` from step 2 to `get_subgraph` so traversal steps are logged. \
Collect the subagent summaries and merge discovered concept IDs. \
Then narrate in 1-2 sentences: the single most significant finding — a missing \
prerequisite, a conflict, or an alternative worth considering.

   **Fallback:** If subagents are not available, call `get_subgraph` directly with \
compact defaults (omit optional parameters for the smallest useful response).

4. **RETRIEVE PASSAGES** — Call `ask_book` scoped to concept IDs discovered in \
step 3, passing `consultation_id` for logging. Use `suggested_questions` from the \
response to ask deterministic follow-up questions derived from graph edges. \
Then narrate in 1-2 sentences: the key insight the book provides.

5. **CHECK COVERAGE** — Call `consultation_report` with the `consultation_id` to \
check coverage gaps before synthesizing. If concept coverage or relationship type \
coverage is low, go back and explore unexplored concepts or missing edge types.

6. **SYNTHESIZE** — Deliver project-specific recommendations:
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
- Prefer compact tool calls: omit optional parameters to get the smallest useful response.
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
            name="match_concepts",
            description=(
                "ENTRY POINT — Deterministically match a project description to knowledge "
                "graph concepts via embedding similarity. Returns ranked concepts with scores "
                "and creates a consultation_id that tracks the session. The same description "
                "always produces the same concept ranking and fingerprint. Pass the returned "
                "consultation_id to get_subgraph and ask_book for step logging."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_description": {
                        "type": "string",
                        "description": "Free-text description of the user's project, architecture, and pain points",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum concepts to return (1-50, default: 15)",
                    },
                    "similarity_threshold": {
                        "type": "number",
                        "description": "Minimum cosine similarity to include (0.0-1.0, default: 0.3)",
                    },
                },
                "required": ["project_description"],
            },
        ),
        Tool(
            name="list_concepts",
            description=(
                "BROWSE — List all 138 concepts in the knowledge graph. Returns compact "
                "output (id, name, category) by default. Use search to filter by name, and "
                "include_definitions for full definition text. Use this to browse the catalogue; "
                "for consultation workflows, prefer match_concepts as the entry point."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "search": {
                        "type": "string",
                        "description": "Filter concepts by name substring (case-insensitive)",
                    },
                    "include_definitions": {
                        "type": "boolean",
                        "description": "Include definition text in output (default: false)",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="get_subgraph",
            description=(
                "QUERY PLANNER — Bounded graph traversal from seed concepts. Given one or "
                "more concept IDs (from match_concepts or list_concepts), performs BFS up to "
                "max_hops and returns all reachable nodes and edges. Use relationship types to "
                "discover what the user is missing: alternative_to for competing approaches, "
                "requires for prerequisites, conflicts_with for incompatibilities, complements "
                "for synergies. Pass consultation_id to log traversal steps for coverage tracking."
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
                        "description": "Minimum edge confidence to traverse (0.0-1.0, default: 0.5)",
                    },
                    "max_edges": {
                        "type": "integer",
                        "description": "Maximum edges to return (1-200, default: 50)",
                    },
                    "include_descriptions": {
                        "type": "boolean",
                        "description": "Include edge description text (default: false)",
                    },
                    "consultation_id": {
                        "type": "string",
                        "description": "Optional consultation ID from match_concepts to log this step",
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
                "get_subgraph for precision. Returns suggested_questions derived deterministically "
                "from graph edges. Pass consultation_id to log retrieval steps."
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
                    "consultation_id": {
                        "type": "string",
                        "description": "Optional consultation ID from match_concepts to log this step",
                    },
                },
                "required": ["question"],
            },
        ),
        Tool(
            name="consultation_report",
            description=(
                "COVERAGE CHECK — Compute coverage metrics for a consultation session. "
                "Shows concept coverage %, relationship type coverage, passage diversity, "
                "whether prerequisite/conflict edges were checked, and specific gaps. "
                "Call before synthesizing to ensure thorough coverage. Optionally compare "
                "two sessions with the same project fingerprint to see diffs."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "consultation_id": {
                        "type": "string",
                        "description": "The consultation session to evaluate",
                    },
                    "compare_to": {
                        "type": "string",
                        "description": "Optional second consultation ID to diff against",
                    },
                },
                "required": ["consultation_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls."""

    if name == "health_check":
        result = await health_check()
        return [TextContent(type="text", text=json.dumps(result, separators=(',', ':')))]

    if name == "match_concepts":
        result = await match_concepts(
            project_description=arguments.get("project_description", ""),
            max_results=arguments.get("max_results", 15),
            similarity_threshold=arguments.get("similarity_threshold", 0.3),
        )
        return [TextContent(type="text", text=json.dumps(result, separators=(',', ':')))]

    if name == "list_concepts":
        result = await list_concepts(
            search=arguments.get("search"),
            include_definitions=arguments.get("include_definitions", False),
        )
        return [TextContent(type="text", text=json.dumps(result, separators=(',', ':')))]

    if name == "get_subgraph":
        result = await get_subgraph(
            concept_ids=arguments.get("concept_ids", []),
            max_hops=arguments.get("max_hops", 2),
            confidence_threshold=arguments.get("confidence_threshold", 0.5),
            max_edges=arguments.get("max_edges", 50),
            include_descriptions=arguments.get("include_descriptions", False),
            consultation_id=arguments.get("consultation_id"),
        )
        return [TextContent(type="text", text=json.dumps(result, separators=(',', ':')))]

    if name == "ask_book":
        result = await ask_book(
            question=arguments.get("question", ""),
            concept_ids=arguments.get("concept_ids"),
            max_passages=arguments.get("max_passages", 3),
            consultation_id=arguments.get("consultation_id"),
        )
        return [TextContent(type="text", text=json.dumps(result, separators=(',', ':')))]

    if name == "consultation_report":
        result = await consultation_report(
            consultation_id=arguments.get("consultation_id", ""),
            compare_to=arguments.get("compare_to"),
        )
        return [TextContent(type="text", text=json.dumps(result, separators=(',', ':')))]

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

2. **Match concepts** — Call `match_concepts` with a concise project description \
summarizing the architecture and pain points you identified. This returns deterministic \
concept rankings and a `consultation_id` for tracking the session.

3. **Traverse the graph (scatter-gather)** — For each matched seed concept, spawn a \
parallel subagent (via the Agent tool) to explore its neighbourhood. Each subagent calls \
`get_subgraph` with that single concept, `include_descriptions=true`, and the \
`consultation_id` from step 2. Analyze relationships and return a compact summary \
(~300 tokens) with key findings and discovered concept IDs. Merge the summaries. \
If subagents are not available, call `get_subgraph` directly with compact defaults. \
Then tell me in 1-2 sentences the single most significant finding from the graph.

4. **Retrieve book passages** — Call `ask_book` scoped to the discovered concept \
IDs, passing the `consultation_id`. Use `suggested_questions` from the response \
to ask deterministic follow-up questions. Cite chapter and page numbers. Then tell \
me in 1-2 sentences the key insight the book provides.

5. **Check coverage** — Call `consultation_report` with the `consultation_id` to \
check coverage gaps. If concept or relationship type coverage is low, go back and \
explore the gaps before synthesizing.

6. **Synthesize recommendations** — Deliver:
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
