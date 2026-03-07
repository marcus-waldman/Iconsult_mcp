"""Test cases derived from openai/openai-agents-python examples.

Each case describes a real-world agent architecture and the iconsult
concepts we expect to surface.  Adding a new test case = adding one
dict to CASES.

Fields
------
id : str            Short slug used as pytest param id.
name : str          Human-readable name.
source : str        GitHub path inside openai-agents-python/examples/.
description : str   Architecture summary fed to match_concepts.
expected_concepts : list[str]
    Concept IDs that MUST appear in the top-15 matches.
    Keep this list short (2-4) — only the most unambiguous signals.
pattern_assessments : list[dict]
    Synthetic pattern_assessment steps for score_architecture tests.
    Each has: pattern_id, pattern_name, status, evidence, maturity_level.
"""

CASES: list[dict] = [
    # ------------------------------------------------------------------
    # 1. Financial Research Agent — hierarchical multi-agent pipeline
    # ------------------------------------------------------------------
    {
        "id": "financial_research",
        "name": "Financial Research Agent",
        "source": "examples/financial_research_agent",
        "description": (
            "A hierarchical multi-agent system for financial research. "
            "A senior writer agent orchestrates sub-analyst agents (fundamentals, "
            "risk) exposed as tools. The pipeline flows: planning -> parallel "
            "web search -> analysis -> writing -> verification by a dedicated "
            "verifier agent. Uses tool-based agent composition and a quality "
            "gate pattern."
        ),
        "expected_concepts": [
            "supervisor_architecture",
            "multi_agent_planning",
            "agent_delegates_to_agent_pattern",
        ],
        "pattern_assessments": [
            {
                "pattern_id": "supervisor_architecture",
                "pattern_name": "Supervisor Architecture",
                "status": "implemented",
                "evidence": "manager.py orchestrates sub-agents",
                "maturity_level": 4,
            },
            {
                "pattern_id": "multi_agent_planning",
                "pattern_name": "Multi-Agent Planning",
                "status": "implemented",
                "evidence": "planner agent creates search strategy",
                "maturity_level": 4,
            },
            {
                "pattern_id": "tool_use_pattern",
                "pattern_name": "Dynamic Tool Selection",
                "status": "implemented",
                "evidence": "agents exposed as tools via as_tool()",
                "maturity_level": 2,
            },
            {
                "pattern_id": "single_agent_baseline_pattern",
                "pattern_name": "Single Agent Baseline",
                "status": "implemented",
                "evidence": "each sub-agent is a single-agent baseline",
                "maturity_level": 1,
            },
            {
                "pattern_id": "watchdog_timeout_pattern",
                "pattern_name": "Watchdog Timeout",
                "status": "missing",
                "evidence": "no timeout handling found",
                "maturity_level": 1,
            },
            {
                "pattern_id": "agent_calls_human_pattern",
                "pattern_name": "Agent Calls Human",
                "status": "missing",
                "evidence": "fully autonomous, no human escalation",
                "maturity_level": 1,
            },
        ],
    },
    # ------------------------------------------------------------------
    # 2. Customer Service — routing / handoff pattern
    # ------------------------------------------------------------------
    {
        "id": "customer_service",
        "name": "Customer Service Agent",
        "source": "examples/customer_service",
        "description": (
            "A customer service agent that routes incoming requests to "
            "specialized sub-agents based on intent classification. Uses "
            "agent handoffs to transfer control between a triage agent and "
            "domain-specific agents (billing, technical support, account). "
            "Demonstrates the router pattern with dynamic agent selection."
        ),
        "expected_concepts": [
            "agent_router_pattern",
        ],
        "pattern_assessments": [
            {
                "pattern_id": "agent_router_pattern",
                "pattern_name": "Agent Router",
                "status": "implemented",
                "evidence": "triage agent routes to domain specialists",
                "maturity_level": 2,
            },
            {
                "pattern_id": "single_agent_baseline_pattern",
                "pattern_name": "Single Agent Baseline",
                "status": "implemented",
                "evidence": "each domain agent is a single-agent baseline",
                "maturity_level": 1,
            },
            {
                "pattern_id": "human_in_the_loop_hitl_pattern",
                "pattern_name": "Human-in-the-Loop",
                "status": "missing",
                "evidence": "no human escalation path",
                "maturity_level": 1,
            },
        ],
    },
    # ------------------------------------------------------------------
    # 3. Research Bot — parallel search with coordinator
    # ------------------------------------------------------------------
    {
        "id": "research_bot",
        "name": "Research Bot",
        "source": "examples/research_bot",
        "description": (
            "A research bot with three specialized agents: a planner that "
            "creates search strategies, multiple search agents that run in "
            "parallel to gather information, and a writer that synthesizes "
            "findings. Managed by a central orchestrator (manager.py). "
            "Demonstrates parallel agent execution and sequential pipeline."
        ),
        "expected_concepts": [
            "multi_agent_planning",
            "supervisor_architecture",
        ],
        "pattern_assessments": [
            {
                "pattern_id": "supervisor_architecture",
                "pattern_name": "Supervisor Architecture",
                "status": "implemented",
                "evidence": "manager.py orchestrates plan/search/write agents",
                "maturity_level": 4,
            },
            {
                "pattern_id": "multi_agent_planning",
                "pattern_name": "Multi-Agent Planning",
                "status": "implemented",
                "evidence": "planner agent creates search items",
                "maturity_level": 4,
            },
            {
                "pattern_id": "single_agent_baseline_pattern",
                "pattern_name": "Single Agent Baseline",
                "status": "implemented",
                "evidence": "search_agent is a single-agent with web search tool",
                "maturity_level": 1,
            },
        ],
    },
    # ------------------------------------------------------------------
    # 4. Deterministic pipeline (agent_patterns/deterministic.py)
    # ------------------------------------------------------------------
    {
        "id": "deterministic_pipeline",
        "name": "Deterministic Pipeline",
        "source": "examples/agent_patterns/deterministic.py",
        "description": (
            "A deterministic multi-step pipeline where each agent's output "
            "feeds into the next agent's input. Breaks down a complex task "
            "into sequential sub-tasks with fixed ordering. No dynamic "
            "routing or branching — pure sequential composition."
        ),
        "expected_concepts": [
            "multi_agent_planning",
        ],
        "pattern_assessments": [
            {
                "pattern_id": "single_agent_baseline_pattern",
                "pattern_name": "Single Agent Baseline",
                "status": "implemented",
                "evidence": "each pipeline stage is a single agent",
                "maturity_level": 1,
            },
        ],
    },
    # ------------------------------------------------------------------
    # 5. Routing pattern (agent_patterns/routing.py)
    # ------------------------------------------------------------------
    {
        "id": "routing",
        "name": "Agent Routing",
        "source": "examples/agent_patterns/routing.py",
        "description": (
            "An agent routing pattern that classifies incoming requests and "
            "hands off to the appropriate specialized agent. Uses handoff "
            "logic to dynamically select which agent handles a request "
            "based on the request's characteristics."
        ),
        "expected_concepts": [
            "agent_router_pattern",
        ],
        "pattern_assessments": [
            {
                "pattern_id": "agent_router_pattern",
                "pattern_name": "Agent Router",
                "status": "implemented",
                "evidence": "routing.py classifies and delegates",
                "maturity_level": 2,
            },
        ],
    },
    # ------------------------------------------------------------------
    # 6. Agents as tools (agent_patterns/agents_as_tools.py)
    # ------------------------------------------------------------------
    {
        "id": "agents_as_tools",
        "name": "Agents as Tools",
        "source": "examples/agent_patterns/agents_as_tools.py",
        "description": (
            "A pattern where agents are invoked as tools rather than via "
            "handoff. An orchestrator agent calls specialist agents (e.g. "
            "translation agents for multiple languages) as tool functions. "
            "The orchestrator retains control and aggregates results, "
            "unlike handoff where control transfers completely."
        ),
        "expected_concepts": [
            "agent_delegates_to_agent_pattern",
            "tool_and_agent_registry",
        ],
        "pattern_assessments": [
            {
                "pattern_id": "tool_use_pattern",
                "pattern_name": "Dynamic Tool Selection",
                "status": "implemented",
                "evidence": "agents exposed via as_tool()",
                "maturity_level": 2,
            },
            {
                "pattern_id": "function_calling_pattern",
                "pattern_name": "Function Calling",
                "status": "implemented",
                "evidence": "tool invocation for agent delegation",
                "maturity_level": 1,
            },
        ],
    },
    # ------------------------------------------------------------------
    # 7. LLM as a Judge (agent_patterns/llm_as_a_judge.py)
    # ------------------------------------------------------------------
    {
        "id": "llm_as_judge",
        "name": "LLM as a Judge",
        "source": "examples/agent_patterns/llm_as_a_judge.py",
        "description": (
            "A quality assurance pattern where a second LLM evaluates and "
            "provides feedback on the output of a first LLM. The judge "
            "agent critiques generated content and the generator iterates "
            "based on feedback. Implements a generate-then-verify loop."
        ),
        "expected_concepts": [
            "instruction_fidelity_auditing_pattern",
            "self_improvement_flywheel",
        ],
        "pattern_assessments": [
            {
                "pattern_id": "structured_reasoning_and_self",
                "pattern_name": "ReAct / Reflexion",
                "status": "partial",
                "evidence": "judge provides feedback but no formal ReAct loop",
                "maturity_level": 3,
            },
            {
                "pattern_id": "instruction_fidelity_auditing_pattern",
                "pattern_name": "Instruction Fidelity Auditing",
                "status": "partial",
                "evidence": "judge checks output quality",
                "maturity_level": 3,
            },
        ],
    },
    # ------------------------------------------------------------------
    # 8. Parallelization (agent_patterns/parallelization.py)
    # ------------------------------------------------------------------
    {
        "id": "parallelization",
        "name": "Parallel Agents",
        "source": "examples/agent_patterns/parallelization.py",
        "description": (
            "Runs a translation agent multiple times in parallel across "
            "different language targets, then uses a judge to pick the best "
            "translation. Demonstrates fan-out/fan-in parallel execution "
            "with majority-voting-style selection."
        ),
        "expected_concepts": [
            "majority_voting_pattern",
        ],
        "pattern_assessments": [
            {
                "pattern_id": "majority_voting_pattern",
                "pattern_name": "Majority Voting Across Agents",
                "status": "partial",
                "evidence": "judge selects best among parallel results (not strict voting)",
                "maturity_level": 6,
            },
        ],
    },
    # ------------------------------------------------------------------
    # 9. Human in the Loop (agent_patterns/human_in_the_loop.py)
    # ------------------------------------------------------------------
    {
        "id": "human_in_the_loop",
        "name": "Human-in-the-Loop",
        "source": "examples/agent_patterns/human_in_the_loop.py",
        "description": (
            "Pauses agent execution runs to request manual human approval "
            "before executing sensitive tools. Implements an approval gate "
            "where the human can accept or reject tool invocations. "
            "Demonstrates the agent-calls-human interaction pattern."
        ),
        "expected_concepts": [
            "human_in_the_loop_hitl",
            "agent_calls_human",
        ],
        "pattern_assessments": [
            {
                "pattern_id": "agent_calls_human_pattern",
                "pattern_name": "Agent Calls Human",
                "status": "implemented",
                "evidence": "approval gate pauses for human input",
                "maturity_level": 1,
            },
            {
                "pattern_id": "human_in_the_loop_hitl_pattern",
                "pattern_name": "Human-in-the-Loop",
                "status": "implemented",
                "evidence": "explicit HITL approval pattern",
                "maturity_level": 1,
            },
        ],
    },
    # ------------------------------------------------------------------
    # 10. Input/Output Guardrails (agent_patterns/input_guardrails.py)
    # ------------------------------------------------------------------
    {
        "id": "guardrails",
        "name": "Input/Output Guardrails",
        "source": "examples/agent_patterns/input_guardrails.py",
        "description": (
            "Validates agent inputs and outputs using guardrail agents. "
            "Input guardrails check requests before processing. Output "
            "guardrails validate responses with tripwire exception support. "
            "Implements safety and compliance checks around agent execution."
        ),
        "expected_concepts": [
            "instruction_fidelity_auditing_pattern",
        ],
        "pattern_assessments": [
            {
                "pattern_id": "instruction_fidelity_auditing_pattern",
                "pattern_name": "Instruction Fidelity Auditing",
                "status": "implemented",
                "evidence": "guardrail agents validate I/O",
                "maturity_level": 3,
            },
        ],
    },
    # ------------------------------------------------------------------
    # 11. Handoffs (examples/handoffs)
    # ------------------------------------------------------------------
    {
        "id": "handoffs",
        "name": "Agent Handoffs",
        "source": "examples/handoffs",
        "description": (
            "Demonstrates agent-to-agent handoff where control transfers "
            "completely from one agent to another. Includes message filtering "
            "during handoffs to control what context transfers. Shows both "
            "standard and streaming handoff variants."
        ),
        "expected_concepts": [
            "agent_delegates_to_agent_pattern",
        ],
        "pattern_assessments": [
            {
                "pattern_id": "agent_delegates_to_agent_pattern",
                "pattern_name": "Agent Delegates to Agent",
                "status": "implemented",
                "evidence": "handoff transfers control between agents",
                "maturity_level": 2,
            },
        ],
    },
    # ------------------------------------------------------------------
    # 12. MCP Integration (examples/mcp)
    # ------------------------------------------------------------------
    {
        "id": "mcp_integration",
        "name": "MCP Tool Integration",
        "source": "examples/mcp",
        "description": (
            "Agents that connect to external services via Model Context "
            "Protocol (MCP) servers. Tools are dynamically discovered and "
            "invoked through a standardized protocol. Demonstrates dynamic "
            "tool registration and external service integration."
        ),
        "expected_concepts": [
            "tool_use_pattern",
            "model_context_protocol_mcp",
        ],
        "pattern_assessments": [
            {
                "pattern_id": "function_calling_pattern",
                "pattern_name": "Function Calling",
                "status": "implemented",
                "evidence": "MCP provides tool calling interface",
                "maturity_level": 1,
            },
            {
                "pattern_id": "tool_use_pattern",
                "pattern_name": "Dynamic Tool Selection",
                "status": "implemented",
                "evidence": "tools dynamically discovered via MCP",
                "maturity_level": 2,
            },
        ],
    },
]

# Quick lookup by case ID
CASES_BY_ID: dict[str, dict] = {c["id"]: c for c in CASES}
