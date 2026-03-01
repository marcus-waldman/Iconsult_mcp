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
from mcp.types import TextContent, Tool

from iconsult_mcp.tools.health import health_check
from iconsult_mcp.tools.list_concepts import list_concepts
from iconsult_mcp.tools.get_subgraph import get_subgraph
from iconsult_mcp.tools.ask_book import ask_book

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

server = Server("iconsult-mcp")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List all available tools."""
    return [
        Tool(
            name="health_check",
            description=(
                "Check iconsult-mcp server health. Returns database connection status, "
                "graph statistics (concept count, relationship count, avg confidence), "
                "and pipeline status."
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
                "List all concepts in the architecture knowledge graph, grouped by category. "
                "Returns concept IDs, names, and definitions. Use this first to browse the "
                "catalogue and identify relevant concepts before calling get_subgraph or ask_book."
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
                "Bounded graph traversal from seed concepts. Given one or more concept IDs "
                "(from list_concepts), performs BFS up to max_hops and returns all reachable "
                "nodes and edges with relationship types, confidence scores, and descriptions. "
                "Use this to discover alternatives, prerequisites, and related patterns."
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
                "RAG search against book sections. Embeds a natural language question and "
                "returns the most relevant book passages with full text content and provenance "
                "(chapter, page numbers, section title). Optionally scope to sections linked "
                "to specific concept IDs for more targeted results."
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
