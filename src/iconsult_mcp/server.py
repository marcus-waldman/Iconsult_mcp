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

from iconsult_mcp.arg_coerce import coerce_typed_args
from iconsult_mcp.config import TOOL_MAX_RETRIES, TOOL_RETRY_BASE_DELAY, TOOL_TIMEOUT_SECONDS

# Exceptions eligible for retry (network/timeout only, not logic errors)
RETRYABLE_EXCEPTIONS = (asyncio.TimeoutError, ConnectionError, TimeoutError, OSError)
from iconsult_mcp.escalation import escalation_response
from iconsult_mcp.tools.health import health_check
from iconsult_mcp.tools.list_concepts import list_concepts
from iconsult_mcp.tools.get_subgraph import get_subgraph
from iconsult_mcp.tools.ask_book import ask_book
from iconsult_mcp.tools.match_concepts import match_concepts
from iconsult_mcp.tools.triage import triage_books
from iconsult_mcp.tools.projects import build_project_kg, list_books, start_project
from iconsult_mcp.tools.consultation_report import consultation_report
from iconsult_mcp.tools.log_pattern_assessment import log_pattern_assessment
from iconsult_mcp.tools.score_architecture import score_architecture
from iconsult_mcp.tools.validate_subagent import validate_subagent
from iconsult_mcp.tools.critique_consultation import critique_consultation
from iconsult_mcp.tools.shared_state import write_state, read_state
from iconsult_mcp.tools.events import emit_event, get_events
from iconsult_mcp.tools.plan_consultation import plan_consultation
from iconsult_mcp.tools.supervise_consultation import supervise_consultation
from iconsult_mcp.tools.failure_scenarios import generate_failure_scenarios
from iconsult_mcp.tools.implementation_plan import (
    generate_implementation_plan,
    get_implementation_plan as get_impl_plan,
    update_plan_step,
)
from iconsult_mcp.tools.blackboard import assert_fact, query_facts
from iconsult_mcp.tools.quality import rate_consultation, consultation_analytics
from iconsult_mcp.tools.render_report import render_report

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Per-tool metadata: timeout overrides, retry eligibility, category, access level
TOOL_METADATA = {
    "health_check": {"timeout": 10, "retryable": False, "category": "diagnostic", "access_level": "admin"},
    "match_concepts": {"timeout": 30, "retryable": True, "category": "consultation", "access_level": "write"},
    "triage_books": {"timeout": 30, "retryable": True, "category": "browse", "access_level": "read"},
    "list_books": {"timeout": 10, "retryable": True, "category": "browse", "access_level": "read"},
    "start_project": {"timeout": 30, "retryable": True, "category": "consultation", "access_level": "write"},
    "build_project_kg": {"timeout": 600, "retryable": False, "category": "consultation", "access_level": "write"},
    "list_concepts": {"timeout": 15, "retryable": True, "category": "browse", "access_level": "read"},
    "get_subgraph": {"timeout": 30, "retryable": True, "category": "consultation", "access_level": "read"},
    "ask_book": {"timeout": 30, "retryable": True, "category": "consultation", "access_level": "read"},
    "consultation_report": {"timeout": 15, "retryable": False, "category": "consultation", "access_level": "read"},
    "score_architecture": {"timeout": 15, "retryable": False, "category": "consultation", "access_level": "read"},
    "log_pattern_assessment": {"timeout": 10, "retryable": False, "category": "consultation", "access_level": "write"},
    "validate_subagent": {"timeout": 5, "retryable": False, "category": "validation", "access_level": "read"},
    "critique_consultation": {"timeout": 10, "retryable": False, "category": "validation", "access_level": "read"},
    "write_state": {"timeout": 10, "retryable": False, "category": "coordination", "access_level": "write"},
    "read_state": {"timeout": 10, "retryable": False, "category": "coordination", "access_level": "read"},
    "emit_event": {"timeout": 10, "retryable": False, "category": "coordination", "access_level": "write"},
    "get_events": {"timeout": 10, "retryable": False, "category": "coordination", "access_level": "read"},
    "plan_consultation": {"timeout": 15, "retryable": False, "category": "consultation", "access_level": "write"},
    "supervise_consultation": {"timeout": 10, "retryable": False, "category": "consultation", "access_level": "read"},
    "generate_failure_scenarios": {"timeout": 15, "retryable": False, "category": "consultation", "access_level": "read"},
    "generate_implementation_plan": {"timeout": 15, "retryable": False, "category": "consultation", "access_level": "write"},
    "get_implementation_plan": {"timeout": 10, "retryable": False, "category": "consultation", "access_level": "read"},
    "update_plan_step": {"timeout": 10, "retryable": False, "category": "consultation", "access_level": "write"},
    "assert_fact": {"timeout": 10, "retryable": False, "category": "coordination", "access_level": "write"},
    "query_facts": {"timeout": 10, "retryable": False, "category": "coordination", "access_level": "read"},
    "rate_consultation": {"timeout": 10, "retryable": False, "category": "quality", "access_level": "write"},
    "consultation_analytics": {"timeout": 10, "retryable": False, "category": "quality", "access_level": "read"},
    "render_report": {"timeout": 30, "retryable": False, "category": "consultation", "access_level": "write"},
}

# Dispatch table: tool name → handler(arguments) → coroutine
TOOL_DISPATCH = {
    "health_check": lambda args: health_check(tool_metadata=TOOL_METADATA),
    "match_concepts": lambda args: match_concepts(
        project_description=args.get("project_description", ""),
        max_results=args.get("max_results", 15),
        similarity_threshold=args.get("similarity_threshold", 0.3),
        project_id=args.get("project_id"),
    ),
    "triage_books": lambda args: triage_books(
        project_description=args.get("project_description", ""),
        top_k=args.get("top_k", 5),
        threshold=args.get("threshold", 0.4),
    ),
    "list_books": lambda args: list_books(
        altitude=args.get("altitude"),
    ),
    "start_project": lambda args: start_project(
        name=args.get("name", ""),
        project_description=args.get("project_description", ""),
        triaged_book_ids=args.get("triaged_book_ids"),
        project_id=args.get("project_id"),
        triage_top_k=args.get("triage_top_k", 5),
        triage_threshold=args.get("triage_threshold", 0.4),
    ),
    "build_project_kg": lambda args: build_project_kg(
        project_id=args.get("project_id", ""),
        force=args.get("force", False),
        auto_align=args.get("auto_align", True),
        align_threshold=args.get("align_threshold", 0.6),
        align_top_k=args.get("align_top_k", 5),
    ),
    "list_concepts": lambda args: list_concepts(
        search=args.get("search"),
        include_definitions=args.get("include_definitions", False),
    ),
    "get_subgraph": lambda args: get_subgraph(
        concept_ids=args.get("concept_ids", []),
        max_hops=args.get("max_hops", 2),
        confidence_threshold=args.get("confidence_threshold", 0.5),
        max_edges=args.get("max_edges", 50),
        include_descriptions=args.get("include_descriptions", False),
        consultation_id=args.get("consultation_id"),
        project_id=args.get("project_id"),
    ),
    "ask_book": lambda args: ask_book(
        question=args.get("question", ""),
        concept_ids=args.get("concept_ids"),
        max_passages=args.get("max_passages", 3),
        consultation_id=args.get("consultation_id"),
        project_id=args.get("project_id"),
    ),
    "consultation_report": lambda args: consultation_report(
        consultation_id=args.get("consultation_id", ""),
        compare_to=args.get("compare_to"),
    ),
    "score_architecture": lambda args: score_architecture(
        consultation_id=args.get("consultation_id", ""),
        target_level=args.get("target_level"),
        roadmap_levels=args.get("roadmap_levels", 3),
    ),
    "log_pattern_assessment": lambda args: log_pattern_assessment(
        consultation_id=args.get("consultation_id", ""),
        pattern_id=args.get("pattern_id", ""),
        pattern_name=args.get("pattern_name", ""),
        status=args.get("status", ""),
        evidence=args.get("evidence", ""),
        maturity_level=args.get("maturity_level", 1),
        failure_context=args.get("failure_context"),
        category=args.get("category", ""),
        indicators=args.get("indicators"),
        source_book_id=args.get("source_book_id"),
        canonical_concept_id=args.get("canonical_concept_id"),
    ),
    "validate_subagent": lambda args: validate_subagent(
        response=args.get("response", {}),
        validate_against_graph=args.get("validate_against_graph", False),
    ),
    "critique_consultation": lambda args: critique_consultation(
        consultation_id=args.get("consultation_id", ""),
        max_iterations=args.get("max_iterations", 1),
    ),
    "write_state": lambda args: write_state(
        consultation_id=args.get("consultation_id", ""),
        key=args.get("key", ""),
        value=args.get("value"),
        agent_id=args.get("agent_id"),
    ),
    "read_state": lambda args: read_state(
        consultation_id=args.get("consultation_id", ""),
        key=args.get("key"),
    ),
    "emit_event": lambda args: emit_event(
        consultation_id=args.get("consultation_id", ""),
        event_type=args.get("event_type", ""),
        data=args.get("data"),
    ),
    "get_events": lambda args: get_events(
        consultation_id=args.get("consultation_id", ""),
        since_id=args.get("since_id"),
        event_type=args.get("event_type"),
    ),
    "plan_consultation": lambda args: plan_consultation(
        consultation_id=args.get("consultation_id", ""),
    ),
    "supervise_consultation": lambda args: supervise_consultation(
        consultation_id=args.get("consultation_id", ""),
    ),
    "generate_failure_scenarios": lambda args: generate_failure_scenarios(
        consultation_id=args.get("consultation_id", ""),
        max_scenarios=args.get("max_scenarios", 5),
    ),
    "generate_implementation_plan": lambda args: generate_implementation_plan(
        consultation_id=args.get("consultation_id", ""),
        output_dir=args.get("output_dir"),
    ),
    "get_implementation_plan": lambda args: get_impl_plan(
        consultation_id=args.get("consultation_id", ""),
    ),
    "update_plan_step": lambda args: update_plan_step(
        consultation_id=args.get("consultation_id", ""),
        step_id=args.get("step_id", ""),
        status=args.get("status", ""),
        notes=args.get("notes", ""),
    ),
    "assert_fact": lambda args: assert_fact(
        consultation_id=args.get("consultation_id", ""),
        fact_type=args.get("fact_type", ""),
        key=args.get("key", ""),
        value=args.get("value"),
        confidence=args.get("confidence", 1.0),
        agent_id=args.get("agent_id"),
        ttl_seconds=args.get("ttl_seconds"),
    ),
    "query_facts": lambda args: query_facts(
        consultation_id=args.get("consultation_id", ""),
        fact_type=args.get("fact_type"),
        key=args.get("key"),
        min_confidence=args.get("min_confidence"),
        detect_conflicts=args.get("detect_conflicts", False),
    ),
    "rate_consultation": lambda args: rate_consultation(
        consultation_id=args.get("consultation_id", ""),
        rating=args.get("rating"),
        feedback=args.get("feedback"),
    ),
    "consultation_analytics": lambda args: consultation_analytics(
        limit=args.get("limit", 20),
    ),
    "render_report": lambda args: render_report(
        consultation_id=args.get("consultation_id", ""),
        title=args.get("title", ""),
        executive_brief=args.get("executive_brief", ""),
        system_description=args.get("system_description", {}),
        agents=args.get("agents", []),
        diagram_current=args.get("diagram_current", ""),
        diagram_target=args.get("diagram_target", ""),
        tooltips_current=args.get("tooltips_current", {}),
        tooltips_target=args.get("tooltips_target", {}),
        recommendation_narratives=args.get("recommendation_narratives"),
        output_dir=args.get("output_dir"),
    ),
}

INSTRUCTIONS = """\
You are an architecture consultant specializing in multi-agent systems. You have \
access to a knowledge graph extracted from "Agentic Architectural Patterns for \
Building Multi-Agent Systems" (Arsanjani & Bustos, Packt 2026) containing 138 \
concepts, their relationships, and full book text.

## Consulting Workflow

1. **READ PROJECT** — Always read the user's codebase first. Understand their \
current architecture, tech stack, and goals before consulting the graph. \
Then narrate: what you found, what stands out (✅ celebrate strengths, 💡 flag \
anything that already hints at opportunities).

2. **MATCH CONCEPTS** — Call `match_concepts` with a concise project description. \
This deterministically embeds the description and returns ranked concept matches with \
a `consultation_id` that tracks the session. The same description always produces the \
same concept ranking. Use `list_concepts` only for browsing/filtering the full catalogue. \
Then narrate: what you're searching for and which top concepts came back — any surprises?

2b. **PLAN** — Call `plan_consultation` with the `consultation_id` from step 2. \
This assesses project complexity (simple/moderate/complex) based on matched concept \
count, description keywords, and relationship density, then generates an adaptive \
step-by-step plan. Follow the generated plan for the remaining steps. The plan \
adjusts traversal depth, subagent usage, and critique requirements based on complexity. \
Optionally call `supervise_consultation` after each major step to track progress and \
get the suggested next action. \
Then narrate: the complexity verdict and what the plan focuses on.

   **Create task list:** Immediately after the plan is generated, use the TaskCreate \
tool to populate the task list so the user can track progress. Create one task per \
plan step, using each step's `description` as the task description. Mark the earlier \
steps (Read Project, Match Concepts, Plan) as already completed since they are done \
by this point. As you complete each subsequent step, mark its task completed before \
moving on.

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
Collect the subagent summaries and merge discovered concept IDs.

   **IMPORTANT — Log pattern assessments:** During traversal, for each architectural \
pattern you identify in the user's codebase (or confirm is missing), call \
`log_pattern_assessment` with the `consultation_id`, `pattern_id`, `pattern_name`, \
`status` ("implemented", "partial", "missing", or "not_applicable"), `evidence`, and \
`maturity_level` (1-6). Use "not_applicable" when a pattern is irrelevant to the \
architecture being assessed (e.g., Agent Calls Human for a fully autonomous batch \
pipeline, or Consensus for a single-supervisor system). Assess as many patterns as you \
can identify from the user's code. These stored assessments are what `score_architecture` \
uses to compute deterministic scores.

   **Capture failure context:** When logging missing or partial patterns, include \
`failure_context` with code references (file:line:snippet for code-grounded consultations) \
and dependency information from `requires` edges. For missing patterns, note what would \
fail — e.g., `{"code_refs": [{"file": "payment.py", "line": 45, "snippet": "resp = \
api.call()"}], "failure_mode": "No retry logic, API failures propagate to orchestrator"}`.

   Then narrate your single biggest 💡 — a prerequisite to strengthen, a \
conflict to address, or an alternative worth exploring. Connect it back to \
something concrete in the codebase (🔗).

   **Shared state:** Use `assert_fact` and `query_facts` (Blackboard Knowledge Hub) for \
typed, versioned subagent coordination — e.g., assert discovered concept IDs, pattern \
findings, or recommendations with confidence scores. Use `query_facts` with \
`detect_conflicts=true` to find disagreements between subagents. Legacy `write_state` \
and `read_state` still work for simple key-value needs. \
Use `emit_event` to signal discoveries (e.g., `gap_found` when an opportunity for \
a key pattern is identified) and `get_events` to poll for reactive suggestions.

   **Fallback:** If subagents are not available, call `get_subgraph` directly with \
compact defaults (omit optional parameters for the smallest useful response).

4. **RETRIEVE PASSAGES** — Call `ask_book` scoped to concept IDs discovered in \
step 3, passing `consultation_id` for logging. Use `suggested_questions` from the \
response to ask deterministic follow-up questions derived from graph edges. \
Then narrate: what the book confirms or adds — especially any 💡 that connects \
a finding from step 3 to a concrete recommendation.

5. **CHECK COVERAGE + SCORE** — Call `consultation_report` with the `consultation_id` to \
check coverage gaps before synthesizing. Concept coverage counts matched concepts that \
were either traversed (get_subgraph) or assessed (log_pattern_assessment). If concept \
coverage or relationship type coverage is low, go back and explore unexplored concepts \
or log more pattern assessments. \
Call `score_architecture` to get the maturity scorecard with current status and goals. \
Call `generate_failure_scenarios` to produce concrete failure walkthroughs for each gap. \
These illustrate how the architecture would benefit from each pattern, using actual \
code paths (code-grounded mode) or book scenarios (book-grounded mode). \
Then narrate: the maturity level, the biggest ✅ strength, and the single most impactful \
💡 opportunity. If coverage was low and you backfilled, note what you went back for.

5b. **CRITIQUE (optional)** — Call `critique_consultation` to get a deterministic quality \
critique of the consultation so far. If errors are found (missing workflow steps, no \
pattern assessments, critical edges unchecked), use the `prompt_mutations` field to \
execute the suggested tool calls and address the gaps. Each mutation specifies an action \
(tool name), params, and reason. Cap this reflection loop at 1 iteration to prevent \
infinite recursion. \
Then narrate briefly: whether the critique passed clean or what you fixed.

6. **SYNTHESIZE** — Call `render_report` with the `consultation_id` and narrative content. \
The tool renders the full HTML report server-side using the reference template and pulls \
structured data (scores, scenarios, coverage) from the database automatically. Provide:
   - **title**: report title (e.g. "MyProject Architecture Consultation")
   - **executive_brief**: 3-4 sentences for a decision maker (what it does well + \
most impactful opportunity + recommended path forward)
   - **system_description**: `{subtitle, architecture, tech_stack, coordination, security}`
   - **agents**: `[{name, icon, color, description, tools}]`
   - **diagram_current** / **diagram_target**: raw Mermaid flowchart definitions \
(blue=existing, red dashed=opportunities, green=new). Color-code with classDef.
   - **tooltips_current** / **tooltips_target**: `{node_id: {title, desc, ref}}` for \
SVG hover tooltips on each node (role, responsibilities, what it does/changes)
   - **recommendation_narratives** (optional): `{pattern_id: description}` for richer \
recommendation cards grounded in the user's specific files
   Do NOT generate raw HTML — the tool handles all CSS, JS, zoom controls, animations, \
and tooltip systems. It returns the file path to the written HTML report.

7. **OFFER IMPLEMENTATION PLAN** — After rendering the HTML report, ask the user \
whether they would like a step-by-step implementation plan. If yes, call \
`generate_implementation_plan`. This produces a phased markdown checklist with steps \
classified as "mechanical" (concrete code changes) or "design_decision" (architectural \
choices needed). After generating, recommend the user start a fresh conversation for \
implementation to keep context clean. In the fresh conversation, use \
`get_implementation_plan` to load the plan and `update_plan_step` to track progress.

## Narration Style — Think Out Loud
Narrate your progress throughout the consultation so the user follows your reasoning in \
real time. Be concise — 1-2 sentences per moment. Use this visual language:

- **Stage transitions**: bold header with icon — `### 🔍 Step 1 — Reading the Codebase`
- **What & why**: "Matching against 138 patterns to find what's relevant to your fan-out \
architecture..."
- **💡 Aha moments**: When you discover something significant — a prerequisite gap, an \
elegant implementation, an unexpected connection — call it out: \
`**💡** The retry logic in handler.py:23 covers HTTP but not the message queue — that's \
a resilience blind spot the Retry pattern would close.`
- **✅ Celebrations**: For implemented patterns: `**✅** Solid retry-with-backoff already \
in place — that's L3 resilience.`
- **🔗 Connections**: When findings link together: `**🔗** This ties back to the supervisor \
gap — both need an explicit escalation path.`
- **⚠️ Tensions**: For conflicts or trade-offs: `**⚠️** Adding consensus here would \
conflict with the latency budget — worth discussing.`

The pattern is: *"This is what I'm doing → this is why → oh! this is what I found."* \
These discovery moments are the value of the consultation — surface them, don't suppress them. \
Narrate at every step transition and whenever something non-obvious emerges.

## Tone and Framing
- Frame the consultation as a **growth roadmap**, not a deficiency report. Lead with \
what the architecture does well before discussing opportunities for improvement.
- Use "opportunity" or "next step" rather than "gap" or "missing" when narrating findings \
to the user. The data structures use technical labels — the narrative should be encouraging.
- Present failure scenarios as **resilience considerations** ("what we can protect against") \
rather than predictions of failure. The goal is to motivate adoption, not alarm.
- Celebrate implemented patterns — they represent real engineering investment and thoughtful \
design decisions.
- Position recommendations as a natural evolution of what's already working, not a criticism \
of what's absent.

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
                "consultation_id to get_subgraph and ask_book for step logging. When "
                "project_id is provided AND the project's unified KG has been built "
                "(build_project_kg), the search runs against the per-project canonical "
                "concept layer (deduplicated across triaged books) and returned concepts "
                "carry member_concept_ids, role, and rubric_pattern_id. When project_id "
                "is omitted, behaviour is identical to the legacy single-book path."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_description": {
                        "type": "string",
                        "description": "Free-text description of the user's project, architecture, and goals",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum concepts to return (1-50, default: 15)",
                    },
                    "similarity_threshold": {
                        "type": "number",
                        "description": "Minimum cosine similarity to include (0.0-1.0, default: 0.3)",
                    },
                    "project_id": {
                        "type": "string",
                        "description": (
                            "Optional. Project ID from start_project. When provided and "
                            "the project's unified KG is built, search runs against the "
                            "project's canonical concept layer instead of the global "
                            "concept space."
                        ),
                    },
                },
                "required": ["project_description"],
            },
        ),
        Tool(
            name="triage_books",
            description=(
                "TRIAGE — Rank registered books by cosine similarity to a project "
                "description. Embeds the description and matches against each "
                "book's summary_embedding. Returns ranked list with scores. Pure "
                "read tool, deterministic, no consultation_id created. With one "
                "book registered the ranking is degenerate; the value emerges as "
                "the corpus grows."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_description": {
                        "type": "string",
                        "description": "Free-text description of the user's project, architecture, and goals",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Maximum books to return (1-50, default: 5)",
                    },
                    "threshold": {
                        "type": "number",
                        "description": "Minimum cosine score to include (0.0-1.0, default: 0.4)",
                    },
                },
                "required": ["project_description"],
            },
        ),
        Tool(
            name="list_books",
            description=(
                "BROWSE — List registered books in the corpus catalogue. "
                "Optional altitude filter ('mid_level', 'implementation', "
                "'strategy', 'domain'). Pure read tool, deterministic, no "
                "consultation_id created. Use this to inspect what books are "
                "available before triage; complements `triage_books` (which "
                "ranks them) and `list_concepts` (which lists concepts within)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "altitude": {
                        "type": "string",
                        "description": "Optional altitude filter (e.g. 'mid_level')",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="start_project",
            description=(
                "START PROJECT — Create or refresh a per-project cache row. "
                "If `triaged_book_ids` is omitted, runs `triage_books` "
                "internally with the same description and stores the ranked "
                "IDs above threshold. Project ID is derived deterministically "
                "from (name, project_description) so calling twice with the "
                "same args is idempotent. Does NOT build the unified KG — "
                "that is `build_project_kg` (Phase 3c, pending). Returns "
                "project_id, the full project row, and (when run) the triage "
                "details. Subsequent consultations on the same project skip "
                "triage and reuse the cached `triaged_book_ids`."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Human-readable project name",
                    },
                    "project_description": {
                        "type": "string",
                        "description": "Free-text project description (also used as triage signal)",
                    },
                    "triaged_book_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Explicit book IDs to scope to (skips internal triage)",
                    },
                    "project_id": {
                        "type": "string",
                        "description": "Optional user-supplied project ID (default: hash of name + description)",
                    },
                    "triage_top_k": {
                        "type": "integer",
                        "description": "Top-k for internal triage when triaged_book_ids omitted (default 5)",
                    },
                    "triage_threshold": {
                        "type": "number",
                        "description": "Cosine threshold for internal triage (default 0.4)",
                    },
                },
                "required": ["name", "project_description"],
            },
        ),
        Tool(
            name="build_project_kg",
            description=(
                "BUILD PROJECT KG — Build the per-project canonical layer for "
                "an existing project. Aligns each pair of triaged books "
                "(cosine-shortlist + Claude adjudication, cached in "
                "concept_alignment_cache so re-runs are fast), runs union-find "
                "over positive verdicts to cluster cross-book equivalents, "
                "writes one canonical_concepts row per cluster (singletons "
                "included) with role classification (supporting_evidence vs "
                "informational_only based on rubric pattern alias hits), and "
                "marks the project as built. Idempotent: skips when "
                "unified_kg_built_at is already set unless `force=True`. "
                "Returns stats and a preview sample of multi-member clusters."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "The project to build the canonical KG for",
                    },
                    "force": {
                        "type": "boolean",
                        "description": "Rebuild even if the KG was previously built (default false)",
                    },
                    "auto_align": {
                        "type": "boolean",
                        "description": "Run alignment for any un-cached book pairs first (default true)",
                    },
                    "align_threshold": {
                        "type": "number",
                        "description": "Cosine cut for alignment shortlisting (default 0.6)",
                    },
                    "align_top_k": {
                        "type": "integer",
                        "description": "Per-side top-k for bidirectional shortlisting (default 5)",
                    },
                },
                "required": ["project_id"],
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
                "discover opportunities: alternative_to for competing approaches, "
                "requires for prerequisites, conflicts_with for incompatibilities, complements "
                "for synergies. Pass consultation_id to log traversal steps for coverage tracking. "
                "When the consultation was opened with a project_id (or project_id is passed "
                "explicitly here) AND the project's unified KG has been built, traversal runs over "
                "the canonical edge view: each canonical seed expands to its source-book members, "
                "BFS runs across raw relationships, and results collapse back to canonical "
                "clusters with one edge per (from_canonical, to_canonical) pair (highest-confidence "
                "source edge wins). Nodes carry member_concept_ids / role / rubric_pattern_id."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "concept_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of concept IDs to start traversal from. When project-scoped, these are canonical concept IDs from match_concepts.",
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
                        "description": "Optional consultation ID from match_concepts to log this step. If the consultation is project-scoped, project_id is auto-picked up from the row.",
                    },
                    "project_id": {
                        "type": "string",
                        "description": "Optional. Project ID from start_project. When provided and the project's unified KG is built, traversal runs over the canonical edge view instead of the raw concept graph. Usually unnecessary — picked up automatically from the consultation row.",
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
                "from graph edges. Pass consultation_id to log retrieval steps. When the "
                "consultation was opened with a project_id (or project_id is passed explicitly here) "
                "AND the project's unified KG has been built, passage search is scoped to the "
                "project's triaged_book_ids and any caller-supplied canonical concept_ids are "
                "expanded to their source-book members; passages carry book_id provenance."
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
                        "description": "Optional: scope search to sections linked to these concept IDs. When project-scoped, these are canonical concept IDs that get expanded to source-book members.",
                    },
                    "max_passages": {
                        "type": "integer",
                        "description": "Maximum number of passages to return (default: 3)",
                    },
                    "consultation_id": {
                        "type": "string",
                        "description": "Optional consultation ID from match_concepts to log this step. If the consultation is project-scoped, project_id is auto-picked up from the row.",
                    },
                    "project_id": {
                        "type": "string",
                        "description": "Optional. Project ID from start_project. When provided and the project's unified KG is built, passage search is scoped to the project's triaged_book_ids and canonical concept_ids are expanded to members. Usually unnecessary — picked up automatically from the consultation row.",
                    },
                },
                "required": ["question"],
            },
        ),
        Tool(
            name="consultation_report",
            description=(
                "COVERAGE CHECK — Compute coverage metrics for a consultation session. "
                "Concept coverage counts matched concepts that were either traversed "
                "(get_subgraph seeds) or assessed (log_pattern_assessment). Also shows "
                "relationship type coverage, passage diversity, prerequisite/conflict "
                "edge checks, and specific gaps. Call before synthesizing to ensure "
                "thorough coverage. Optionally compare two sessions with the same "
                "project fingerprint to see diffs."
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
        Tool(
            name="score_architecture",
            description=(
                "MATURITY SCORECARD — Deterministic architecture scoring from stored pattern "
                "assessments. Reads pattern_assessment steps logged during graph traversal and "
                "computes: maturity level (L1-L6), pattern status with goals (target status "
                "after recommendations), gap analysis with severity, recommended metrics from "
                "the book, and implementation roadmap. Same consultation always produces same "
                "results. Requires pattern_assessment steps to have been logged during step 3 "
                "(traverse graph)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "consultation_id": {
                        "type": "string",
                        "description": "The consultation session to score",
                    },
                    "target_level": {
                        "type": "integer",
                        "description": "Override target maturity level (1-6, default: current + 1)",
                    },
                    "roadmap_levels": {
                        "type": "integer",
                        "description": (
                            "Number of maturity levels the roadmap covers (1-6, default: 3). "
                            "Controls the scope of Goal column and implementation phases."
                        ),
                    },
                },
                "required": ["consultation_id"],
            },
        ),
        Tool(
            name="log_pattern_assessment",
            description=(
                "LOG ASSESSMENT — Record a pattern assessment for a consultation session. "
                "Call this during graph traversal (step 3) for each architectural pattern you "
                "identify in the user's codebase or confirm is missing. These stored assessments "
                "are what score_architecture uses to compute deterministic maturity scores."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "consultation_id": {
                        "type": "string",
                        "description": "The consultation session ID from match_concepts",
                    },
                    "pattern_id": {
                        "type": "string",
                        "description": "The concept ID of the pattern being assessed",
                    },
                    "pattern_name": {
                        "type": "string",
                        "description": "Human-readable name of the pattern",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["implemented", "partial", "missing", "not_applicable"],
                        "description": (
                            "Whether the pattern is implemented, partial, missing, or "
                            "not_applicable (pattern is irrelevant to this architecture, "
                            "e.g. Agent Calls Human for a batch pipeline)"
                        ),
                    },
                    "evidence": {
                        "type": "string",
                        "description": "File path or description of what was found (or not found)",
                    },
                    "maturity_level": {
                        "type": "integer",
                        "description": "Assessed maturity level (1-6, default: 1)",
                    },
                    "failure_context": {
                        "type": "object",
                        "description": (
                            "Optional structured failure context for stress test demos. "
                            "Fields: code_refs (list of {file, line, snippet}), "
                            "failure_mode (string describing what breaks), "
                            "depends_on (list of pattern_ids this depends on)"
                        ),
                    },
                    "category": {
                        "type": "string",
                        "description": (
                            "Optional. Rubric category key (e.g., 'coordination', "
                            "'robustness'). Auto-resolved from pattern_id via the "
                            "Ch. 12 rubric if omitted."
                        ),
                    },
                    "indicators": {
                        "type": "array",
                        "description": (
                            "Optional. Binary indicator assessments from the Ch. 12 "
                            "rubric for this pattern. Each entry: "
                            "{text: string, met: bool, na: bool (optional)}. When "
                            "supplied (and status is not 'not_applicable'), status "
                            "is auto-computed: all met -> 'implemented', else -> "
                            "'missing'. Surfaced into score_architecture's "
                            "missing_indicators per-pattern gap analysis."
                        ),
                        "items": {"type": "object"},
                    },
                    "source_book_id": {
                        "type": "string",
                        "description": (
                            "Optional. Which book this pattern's evidence came from "
                            "(e.g., 'gulli_2025'). Pure provenance — no validation, "
                            "no behaviour change to score_architecture. Surfaced "
                            "downstream into failure_scenarios and render_report "
                            "for attribution in multi-book consultations."
                        ),
                    },
                    "canonical_concept_id": {
                        "type": "string",
                        "description": (
                            "Optional. The canonical cluster ID "
                            "({project_id}__{slug}) the assessed concept belongs to "
                            "in a project-scoped consultation. Pure provenance."
                        ),
                    },
                },
                "required": ["consultation_id", "pattern_id", "pattern_name", "status"],
            },
        ),
        Tool(
            name="validate_subagent",
            description=(
                "VALIDATE — Schema validation for subagent responses from scatter-gather "
                "graph traversal. Checks that a subagent response contains the required "
                "fields (concept, key_relationships, recommendation, discovered_ids) with "
                "correct types. Returns validation result with errors and warnings. "
                "No LLM calls — pure structural validation."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "response": {
                        "type": "object",
                        "description": "The JSON object returned by a graph-analysis subagent",
                    },
                    "validate_against_graph": {
                        "type": "boolean",
                        "description": "Also verify discovered_ids and concept against the knowledge graph (default false)",
                    },
                },
                "required": ["response"],
            },
        ),
        Tool(
            name="critique_consultation",
            description=(
                "CRITIQUE — Deterministic quality critique of a consultation session. "
                "Analyzes logged steps for workflow completeness, traversal depth, "
                "pattern assessment coverage, passage diversity, and critical edge checks. "
                "Returns issues with severity (error/warning), categories, and actionable "
                "suggestions. No LLM calls — pure structural analysis."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "consultation_id": {
                        "type": "string",
                        "description": "The consultation session to critique",
                    },
                    "max_iterations": {
                        "type": "integer",
                        "description": "Number of critique iterations (1-3, default 1). Stops early if converged or stuck.",
                    },
                },
                "required": ["consultation_id"],
            },
        ),
        Tool(
            name="write_state",
            description=(
                "SHARED STATE (write) — Upsert a key-value pair in consultation shared "
                "state. Use for subagent coordination: store discovered concepts, current "
                "phase, conflict markers, or any JSON-serializable value. Logs a state_write "
                "step to the consultation."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "consultation_id": {
                        "type": "string",
                        "description": "The consultation session ID",
                    },
                    "key": {
                        "type": "string",
                        "description": "State key (e.g. 'discovered_concepts', 'current_phase')",
                    },
                    "value": {
                        "description": "Any JSON-serializable value to store",
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "Optional agent identifier; when provided, also bridges to blackboard",
                    },
                },
                "required": ["consultation_id", "key", "value"],
            },
        ),
        Tool(
            name="read_state",
            description=(
                "SHARED STATE (read) — Read shared state from a consultation. "
                "Returns one entry if key is specified, or all entries if omitted. "
                "Use for subagent coordination and progress tracking."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "consultation_id": {
                        "type": "string",
                        "description": "The consultation session ID",
                    },
                    "key": {
                        "type": "string",
                        "description": "Specific key to read (omit for all entries)",
                    },
                },
                "required": ["consultation_id"],
            },
        ),
        Tool(
            name="emit_event",
            description=(
                "EVENT (emit) — Emit a consultation event for reactive processing. "
                "Valid types: gap_found, pattern_assessed, coverage_threshold_reached, "
                "coverage_dropped, plan_created, state_conflict. Returns a reactive "
                "suggestion based on the event type."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "consultation_id": {
                        "type": "string",
                        "description": "The consultation session ID",
                    },
                    "event_type": {
                        "type": "string",
                        "enum": [
                            "gap_found", "pattern_assessed",
                            "coverage_threshold_reached", "coverage_dropped",
                            "plan_created", "state_conflict",
                        ],
                        "description": "Type of event to emit",
                    },
                    "data": {
                        "type": "object",
                        "description": "Optional event payload (JSON object)",
                    },
                },
                "required": ["consultation_id", "event_type"],
            },
        ),
        Tool(
            name="get_events",
            description=(
                "EVENT (poll) — Poll consultation events with optional filters. "
                "Use since_id to get only new events since a previous poll. "
                "Use event_type to filter by type."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "consultation_id": {
                        "type": "string",
                        "description": "The consultation session ID",
                    },
                    "since_id": {
                        "type": "integer",
                        "description": "Only return events with id > since_id",
                    },
                    "event_type": {
                        "type": "string",
                        "description": "Filter by event type",
                    },
                },
                "required": ["consultation_id"],
            },
        ),
        Tool(
            name="plan_consultation",
            description=(
                "PLAN — Generate an adaptive consultation plan after match_concepts. "
                "Assesses project complexity (simple/moderate/complex) based on concept "
                "count, description keywords, and relationship density. Returns a "
                "step-by-step plan with tool names and parameters. Call once after "
                "match_concepts, then follow the generated plan."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "consultation_id": {
                        "type": "string",
                        "description": "The consultation session ID from match_concepts",
                    },
                },
                "required": ["consultation_id"],
            },
        ),
        Tool(
            name="supervise_consultation",
            description=(
                "SUPERVISE — Track consultation progress and suggest the next action. "
                "Returns workflow phase progress (percent complete), the recommended "
                "next tool call with parameters, step summary, recent event alerts, "
                "and shared state entries. Call after each major step for guided workflow."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "consultation_id": {
                        "type": "string",
                        "description": "The consultation session ID",
                    },
                },
                "required": ["consultation_id"],
            },
        ),
        Tool(
            name="generate_failure_scenarios",
            description=(
                "RESILIENCE ANALYSIS — Generate concrete scenario walkthroughs for "
                "patterns not yet in place. Each scenario illustrates how the architecture "
                "would respond under stress: trigger event, step-by-step propagation through "
                "the architecture (with file:line references when code evidence is available), "
                "potential impact, and book-cited recommendations. Also maps coverage against "
                "Ch. 7's five-step failure recovery chain. Notes foundation dependencies "
                "when advanced patterns rely on patterns not yet implemented. Deterministic — "
                "same consultation always produces same scenarios. Requires pattern_assessment "
                "steps from step 3."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "consultation_id": {
                        "type": "string",
                        "description": "The consultation session to analyze",
                    },
                    "max_scenarios": {
                        "type": "integer",
                        "description": "Maximum scenarios to return (1-20, default: 5)",
                    },
                },
                "required": ["consultation_id"],
            },
        ),
        Tool(
            name="generate_implementation_plan",
            description=(
                "IMPLEMENTATION PLAN — Generate a phased, classified implementation plan "
                "from consultation results. Builds on score_architecture internals to produce "
                "a markdown checklist with steps classified as 'mechanical' (concrete code "
                "changes) or 'design_decision' (architectural choices needed). Writes markdown "
                "to disk and stores plan in DuckDB for cross-session tracking. Requires "
                "pattern_assessment steps from step 3."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "consultation_id": {
                        "type": "string",
                        "description": "The consultation session to generate a plan for",
                    },
                    "output_dir": {
                        "type": "string",
                        "description": "Directory for markdown file (default: ~/.agent/diagrams/)",
                    },
                },
                "required": ["consultation_id"],
            },
        ),
        Tool(
            name="get_implementation_plan",
            description=(
                "GET PLAN — Retrieve a previously generated implementation plan with "
                "current progress. Returns the full plan JSON, markdown file path, "
                "timestamps, and progress summary."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "consultation_id": {
                        "type": "string",
                        "description": "The consultation session to retrieve the plan for",
                    },
                },
                "required": ["consultation_id"],
            },
        ),
        Tool(
            name="update_plan_step",
            description=(
                "UPDATE STEP — Update the status of a step in an implementation plan. "
                "Tracks progress across conversations. Updates both the DuckDB record "
                "and the markdown file on disk."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "consultation_id": {
                        "type": "string",
                        "description": "The consultation session",
                    },
                    "step_id": {
                        "type": "string",
                        "description": "The step to update (e.g. '1.1')",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "completed", "skipped"],
                        "description": "New status for the step",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional notes about the update",
                    },
                },
                "required": ["consultation_id", "step_id", "status"],
            },
        ),
        Tool(
            name="assert_fact",
            description=(
                "BLACKBOARD (assert) — Assert a typed, versioned fact on the blackboard. "
                "Append-only (never overwrites). Multiple agents can assert different values "
                "for the same key. Use query_facts with detect_conflicts to find disagreements."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "consultation_id": {
                        "type": "string",
                        "description": "The consultation session",
                    },
                    "fact_type": {
                        "type": "string",
                        "description": "Category of fact (e.g., 'concept_finding', 'pattern_status', 'recommendation')",
                    },
                    "key": {
                        "type": "string",
                        "description": "Fact key (e.g., a concept ID or pattern ID)",
                    },
                    "value": {
                        "description": "Arbitrary JSON-serializable value",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Confidence score 0.0-1.0 (default 1.0)",
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "Identifier of the subagent asserting this fact",
                    },
                    "ttl_seconds": {
                        "type": "integer",
                        "description": "Optional time-to-live in seconds",
                    },
                },
                "required": ["consultation_id", "fact_type", "key", "value"],
            },
        ),
        Tool(
            name="query_facts",
            description=(
                "BLACKBOARD (query) — Query facts from the blackboard with optional filters. "
                "Supports conflict detection (different agents asserting different values for "
                "the same key) and convergence summary."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "consultation_id": {
                        "type": "string",
                        "description": "The consultation session",
                    },
                    "fact_type": {
                        "type": "string",
                        "description": "Filter by fact type",
                    },
                    "key": {
                        "type": "string",
                        "description": "Filter by key",
                    },
                    "min_confidence": {
                        "type": "number",
                        "description": "Minimum confidence threshold",
                    },
                    "detect_conflicts": {
                        "type": "boolean",
                        "description": "Include conflict detection and convergence summary (default false)",
                    },
                },
                "required": ["consultation_id"],
            },
        ),
        Tool(
            name="rate_consultation",
            description=(
                "QUALITY (rate) — Rate a consultation's quality with a 1-5 score and/or "
                "free-text feedback. Automatically snapshots consultation metadata for trend analysis."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "consultation_id": {
                        "type": "string",
                        "description": "The consultation session to rate",
                    },
                    "rating": {
                        "type": "integer",
                        "description": "Quality score 1-5",
                        "minimum": 1,
                        "maximum": 5,
                    },
                    "feedback": {
                        "type": "string",
                        "description": "Free-text feedback about the consultation",
                    },
                },
                "required": ["consultation_id"],
            },
        ),
        Tool(
            name="consultation_analytics",
            description=(
                "QUALITY (analytics) — Surface quality trends across consultations. "
                "Returns recent ratings with aggregate statistics (average rating, coverage, "
                "pattern counts, rating distribution)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of recent ratings to return (default 20)",
                    },
                },
            },
        ),
        Tool(
            name="render_report",
            description=(
                "RENDER REPORT — Server-side HTML report rendering. Pulls structured data "
                "(scores, scenarios, coverage) from the database and merges with Claude-provided "
                "narrative content to produce a complete HTML report with all CSS, JS, zoom "
                "controls, SVG tooltips, and animations. Claude provides only ~1700 tokens of "
                "narrative; the tool handles the rest. Returns the file path."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "consultation_id": {
                        "type": "string",
                        "description": "The consultation session to render",
                    },
                    "title": {
                        "type": "string",
                        "description": "Report title (e.g. 'MyProject Architecture Consultation')",
                    },
                    "executive_brief": {
                        "type": "string",
                        "description": "3-4 sentence executive summary for decision makers",
                    },
                    "system_description": {
                        "type": "object",
                        "description": "System details: {subtitle, architecture, tech_stack, coordination, security}",
                    },
                    "agents": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Agent roster: [{name, icon, color, description, tools}]",
                    },
                    "diagram_current": {
                        "type": "string",
                        "description": "Raw Mermaid flowchart definition for current architecture",
                    },
                    "diagram_target": {
                        "type": "string",
                        "description": "Raw Mermaid flowchart definition for target architecture",
                    },
                    "tooltips_current": {
                        "type": "object",
                        "description": "SVG tooltip metadata for current diagram: {node_id: {title, desc, ref}}",
                    },
                    "tooltips_target": {
                        "type": "object",
                        "description": "SVG tooltip metadata for target diagram: {node_id: {title, desc, ref}}",
                    },
                    "recommendation_narratives": {
                        "type": "object",
                        "description": "Optional {pattern_id: description} for richer recommendation cards",
                    },
                    "output_dir": {
                        "type": "string",
                        "description": "Output directory (default: ~/.agent/diagrams/)",
                    },
                },
                "required": ["consultation_id", "title", "executive_brief", "system_description",
                             "agents", "diagram_current", "diagram_target",
                             "tooltips_current", "tooltips_target"],
            },
        ),
    ]


# Cached map of tool name -> inputSchema, populated lazily on first
# call_tool invocation. Used by the defensive arg-coercion path to
# JSON-decode string-encoded array / integer / number / boolean values
# that some MCP harnesses (notably Claude Code) ship as strings.
_TOOL_SCHEMAS: dict[str, dict] | None = None


async def _get_tool_schemas() -> dict[str, dict]:
    """Lazy schema cache built from list_tools()."""
    global _TOOL_SCHEMAS
    if _TOOL_SCHEMAS is None:
        tools = await list_tools()
        _TOOL_SCHEMAS = {t.name: t.inputSchema for t in tools}
    return _TOOL_SCHEMAS


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls via dispatch table with timeout protection."""
    handler = TOOL_DISPATCH.get(name)
    if handler is None:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    # Defensive coercion: some MCP harnesses JSON-encode array/integer/
    # number/boolean params as strings before they reach the server.
    # Decode them based on the tool's declared schema so individual tools
    # don't have to defend against the harness quirk.
    schemas = await _get_tool_schemas()
    arguments = coerce_typed_args(arguments, schemas.get(name))

    meta = TOOL_METADATA.get(name, {})
    timeout = meta.get("timeout", TOOL_TIMEOUT_SECONDS)
    retryable = meta.get("retryable", False)
    max_retries = TOOL_MAX_RETRIES if retryable else 0

    last_exc: Exception | None = None
    for attempt in range(1 + max_retries):
        try:
            result = await asyncio.wait_for(handler(arguments), timeout=timeout)
            return [TextContent(type="text", text=json.dumps(result, separators=(',', ':')))]
        except RETRYABLE_EXCEPTIONS as exc:
            last_exc = exc
            if attempt < max_retries:
                delay = TOOL_RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    f"Tool '{name}' attempt {attempt + 1} failed ({type(exc).__name__}), "
                    f"retrying in {delay:.1f}s"
                )
                await asyncio.sleep(delay)
            # Fall through to escalation on final attempt
        except Exception as exc:
            last_exc = exc
            break  # Non-retryable exception, escalate immediately

    result = escalation_response(
        tool=name,
        error=last_exc,
        timeout_seconds=timeout if isinstance(last_exc, asyncio.TimeoutError) else None,
        retryable=retryable,
    )
    return [TextContent(type="text", text=json.dumps(result, separators=(',', ':')))]


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
                        "what you're trying to achieve, and any challenges or goals."
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
architecture, tech stack, and patterns in use. Then think out loud: what you found, \
what stands out — celebrate (✅) what's strong and flag (💡) anything that hints at \
opportunities.

2. **Match concepts** — Call `match_concepts` with a concise project description \
summarizing the architecture and goals you identified. This returns deterministic \
concept rankings and a `consultation_id` for tracking the session. Then think out loud: \
what you searched for and which top concepts came back — any surprises?

2b. **Plan** — Call `plan_consultation` with the `consultation_id`. This assesses \
complexity and generates an adaptive plan. Follow the plan for remaining steps. \
Optionally call `supervise_consultation` after each major step for progress tracking. \
Then tell me: the complexity verdict and what the plan focuses on. \
**Immediately after the plan is generated**, use the TaskCreate tool to populate the \
task list so I can track your progress. Create one task per plan step using each step's \
`description`. Mark earlier steps (Read Project, Match Concepts, Plan) as already \
completed. Mark each subsequent task completed as you finish it.

3. **Traverse the graph (scatter-gather)** — For each matched seed concept, spawn a \
parallel subagent (via the Agent tool) to explore its neighbourhood. Each subagent calls \
`get_subgraph` with that single concept, `include_descriptions=true`, and the \
`consultation_id` from step 2. Analyze relationships and return a compact summary \
(~300 tokens) with key findings and discovered concept IDs. Merge the summaries. \
If subagents are not available, call `get_subgraph` directly with compact defaults. \
**IMPORTANT:** During traversal, call `log_pattern_assessment` for each pattern you \
identify in my codebase (or confirm is not yet present). This enables deterministic \
scoring. Use `write_state`/`read_state` for subagent coordination and `emit_event` to \
signal discoveries (e.g., `gap_found` when an opportunity for a key pattern is identified). \
Then tell me your single biggest 💡 from the graph — what surprised you or \
what connects back (🔗) to something concrete in my codebase.

4. **Retrieve book passages** — Call `ask_book` scoped to the discovered concept \
IDs, passing the `consultation_id`. Use `suggested_questions` from the response \
to ask deterministic follow-up questions. Cite chapter and page numbers. Then tell \
me: what the book confirms or adds — especially any 💡 that connects a graph finding \
to a concrete recommendation.

5. **Check coverage and score** — Call `consultation_report` with the `consultation_id` \
to check coverage. Then call `score_architecture` to get the maturity scorecard \
with current status and goals. If coverage is low, go back and explore further. \
Then call `generate_failure_scenarios` to produce concrete resilience scenarios — \
these illustrate how the architecture would benefit from each pattern, using code \
references or book scenarios. Then tell me: the maturity level, the biggest ✅ strength, \
and the single most impactful 💡 opportunity.

6. **Synthesize recommendations** — Render the entire consultation as a **single \
self-contained HTML page** using `/generate-web-diagram` (opens in browser). \
**Before generating**, read the reference template at \
`templates/consultation-report.html` in the Iconsult MCP repo (search for it via \
`glob **/Iconsult_mcp/templates/consultation-report.html`). Replicate its exact HTML \
structure, CSS, and JS patterns. Use ASCII only for trivial diagrams with fewer than \
~5 nodes. The HTML page must include, in order:
   a. **Executive Brief** — 3-4 sentence callout box: what the system is, what it does well, \
the single most impactful opportunity, the recommended path forward. For decision makers.
   b. **Maturity banner** — Current level and target level.
   c. **System Under Review** — What the system does, its architecture, tech stack, agent \
roster with roles and tool sets.
   d. **Maturity Scorecard table** — Pattern, Level, Status, Goal, Phase, Evidence. Every \
pattern name must have a **hover tooltip** with: (1) pattern definition, (2) if implemented: \
how it's done in this codebase; if partial: what's done + what's missing; if missing: why \
it matters for this system, (3) book reference with chapter/page.
   e. **Before/After architecture diagrams** — Stacked Mermaid flowcharts (current on \
top, target below — never side-by-side, as side-by-side renders too small to read) with \
interactive hover tooltips on every node. Each tooltip shows the agent/component's role, \
responsibilities, and why it matters. Current diagram: what it does today. Target diagram: \
what changes or gets added. Use styled HTML tooltips on the rendered SVG, not browser-native \
title attributes — use the "Mermaid SVG Node Tooltips" pattern from css-patterns.md \
(JSON metadata block + post-render JS). Include zoom controls (+/−/reset buttons) and \
Ctrl+scroll-to-zoom on each diagram container, plus drag-to-pan when zoomed. Use CSS \
`transform: scale()` via a `--diagram-zoom` CSS custom property (not CSS `zoom`, \
which doesn't work on SVG elements). See the reference template for the exact pattern.
   f. **Implementation Recommendations** — Cards grouped by phase with priority badges, \
code snippets, file refs, book citations.
   g. **Failure Recovery Chain** from Ch. 7.
   h. **Stress Test: Failure Scenarios** — Collapsible failure cascade traces for each \
CRITICAL/WARNING gap. Each trace: trigger, propagation steps with file:line refs, \
impact, book citation, recovery recommendation. Include Ch. 7 failure chain coverage \
diagram and inverted pyramid warnings.
   - Prerequisites check (requires edges) and conflict warnings (conflicts_with edges)
   - Comparison of alternatives rendered as HTML table when 4+ rows or 3+ columns

7. **Implementation plan** — Ask me whether I'd like a concrete implementation plan. \
If yes, call `generate_implementation_plan`. Then recommend a fresh conversation for \
implementation using `get_implementation_plan` and `update_plan_step`.""",
                ),
            ),
        ],
    )


async def run_server():
    """Run the MCP server."""
    # Warm up MotherDuck connection before accepting tool calls.
    # get_connection() is blocking (network I/O to MotherDuck cold-start),
    # so run it in a thread to avoid stalling the event loop.
    from iconsult_mcp.db import get_connection
    try:
        await asyncio.to_thread(get_connection)
        logger.info("MotherDuck connection warmed up")
    except Exception as e:
        logger.warning(f"MotherDuck warm-up failed ({e}), will retry on first tool call")

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
