"""
Extract binary indicators per pattern from Ch. 12 + source chapters.

One-time pipeline script. For each pattern in the Ch. 12 rubric, queries
the relevant chapter sections from the DB and uses Claude to extract 2-5
binary indicators that can be verified by examining source code.

Output: src/iconsult_mcp/tools/rubric_data.py

Usage:
    py scripts/extract_indicators.py              # extract all
    py scripts/extract_indicators.py --dry-run    # show patterns, skip Claude
    py scripts/extract_indicators.py --category robustness  # one category
"""

import argparse
import asyncio
import json
import re
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from iconsult_mcp.db import get_connection
from iconsult_mcp.embed import claude_messages

# ---------------------------------------------------------------------------
# Ch. 12 rubric: category -> level -> patterns with source chapter + context
# ---------------------------------------------------------------------------

CH12_RUBRIC: dict[str, dict] = {
    "coordination": {
        "name": "Coordination & Planning",
        "source_chapter": 5,
        "levels": {
            "basic": [
                {
                    "id": "supervisor_architecture",
                    "name": "Supervisor Architecture",
                    "ch12_context": (
                        "Task Delegation Framework (Supervisor Architecture): "
                        "This is the natural starting point. A single, central orchestrator "
                        "agent is responsible for the entire workflow, providing a clear chain "
                        "of command."
                    ),
                },
                {
                    "id": "multi_agent_planning",
                    "name": "Multi-Agent Planning",
                    "ch12_context": (
                        "Multi-Agent Planning: The orchestrator uses this pattern to perform "
                        "basic task decomposition, breaking a user's request into a hardcoded "
                        "or simple, dynamic sequence of steps."
                    ),
                },
            ],
            "intermediate": [
                {
                    "id": "hybrid_delegation_framework",
                    "name": "Hybrid Delegation Framework",
                    "ch12_context": (
                        "Hybrid Delegation Framework: The system may evolve to a hybrid model "
                        "where a top-level orchestrator delegates tasks to self-organizing "
                        "swarms or 'crews' of agents."
                    ),
                },
                {
                    "id": "shared_epistemic_memory",
                    "name": "Shared Epistemic Memory",
                    "ch12_context": (
                        "Knowledge Sharing: A simple in-memory state is replaced by a "
                        "persistent, Shared Epistemic Memory (e.g., a Redis cache or a "
                        "dedicated database) that all agents can access. This implementation "
                        "must include concurrency controls to prevent race conditions, "
                        "Time-to-Live (TTL) policies for data hygiene, and semantic indexing "
                        "to ensure efficient retrieval."
                    ),
                },
            ],
            "advanced": [
                {
                    "id": "consensus_and_negotiation",
                    "name": "Consensus, Negotiation & Conflict Resolution",
                    "ch12_context": (
                        "Consensus, Negotiation, and Conflict Resolution: The system now has "
                        "the 'social' skills to handle ambiguity and disagreement autonomously. "
                        "Agents can debate conflicting data, negotiate for resources, and "
                        "resolve conflicting plans without needing a top-down directive."
                    ),
                },
            ],
        },
    },
    "explainability": {
        "name": "Explainability & Compliance",
        "source_chapter": 6,
        "levels": {
            "basic": [
                {
                    "id": "basic_audit_logging",
                    "name": "Basic Audit Logging",
                    "ch12_context": (
                        "Basic Audit Logging: While a full Causal Dependency Graph may be "
                        "overkill, every action and decision must be logged to a file or "
                        "console with timestamps, agent IDs, and outcomes. This is the "
                        "non-negotiable minimum for debugging and accountability."
                    ),
                },
            ],
            "intermediate": [
                {
                    "id": "instruction_fidelity_auditing",
                    "name": "Instruction Fidelity Auditing",
                    "ch12_context": (
                        "Instruction Fidelity Auditing and Persistent Instruction Anchoring: "
                        "These are now formally implemented to prevent instruction drift in "
                        "more complex, multi-hop workflows."
                    ),
                },
                {
                    "id": "persistent_instruction_anchoring",
                    "name": "Persistent Instruction Anchoring",
                    "ch12_context": (
                        "Persistent Instruction Anchoring: Formally implemented alongside "
                        "Instruction Fidelity Auditing to prevent instruction drift in "
                        "multi-hop workflows."
                    ),
                },
                {
                    "id": "causal_dependency_graph",
                    "name": "Causal Dependency Graph",
                    "source_chapter_override": 7,
                    "ch12_context": (
                        "Causal Dependency Graph: Basic logging is upgraded to a structured, "
                        "auditable graph that traces the full lineage of every decision."
                    ),
                },
            ],
            "advanced": [
                {
                    "id": "fractal_cot_embedding",
                    "name": "Fractal CoT Embedding",
                    "ch12_context": (
                        "Fractal CoT Embedding: Agents use this advanced reasoning pattern "
                        "for recursive self-correction, enabling them to catch their own "
                        "logical flaws and revise their plans based on new evidence."
                    ),
                },
            ],
        },
    },
    "robustness": {
        "name": "Robustness & Fault Tolerance",
        "source_chapter": 7,
        "levels": {
            "basic": [
                {
                    "id": "watchdog_timeout",
                    "name": "Watchdog Timeout",
                    "ch12_context": (
                        "Watchdog Timeout Supervisor: This is a critical safety net. Wrap all "
                        "agent calls, especially those involving external APIs, with a timeout "
                        "to prevent a single hanging agent from freezing the entire application."
                    ),
                },
                {
                    "id": "simple_retry",
                    "name": "Simple Retry Mechanism",
                    "ch12_context": (
                        "Simple Retry Mechanism: Implement a basic loop to retry a failed task "
                        "a fixed number of times. This handles transient network errors or API "
                        "blips."
                    ),
                },
            ],
            "intermediate": [
                {
                    "id": "adaptive_retry_with_prompt_mutation",
                    "name": "Adaptive Retry with Prompt Mutation",
                    "ch12_context": (
                        "Adaptive Retry with Prompt Mutation: Simple retries are enhanced with "
                        "logic to modify the prompt on failure."
                    ),
                },
                {
                    "id": "auto_healing_agent_resuscitation",
                    "name": "Auto-Healing Agent Resuscitation",
                    "ch12_context": (
                        "Auto-Healing Agent Resuscitation and Incremental Checkpointing: The "
                        "system can now automatically restart crashed agent services and resume "
                        "long-running tasks from the last saved state. To prevent infinite "
                        "'crash loops' caused by persistent errors, this mechanism must be "
                        "governed by exponential backoff strategies and maximum retry thresholds."
                    ),
                },
                {
                    "id": "incremental_checkpointing",
                    "name": "Incremental Checkpointing",
                    "ch12_context": (
                        "Incremental Checkpointing: The system can resume long-running tasks "
                        "from the last saved state after a crash or restart."
                    ),
                },
                {
                    "id": "fallback_model_invocation",
                    "name": "Fallback Model Invocation",
                    "ch12_context": (
                        "Fallback Model Invocation: Provides a business continuity plan for "
                        "LLM API outages."
                    ),
                },
                {
                    "id": "rate_limited_invocation",
                    "name": "Rate-Limited Invocation",
                    "ch12_context": (
                        "Rate-Limited Invocation: Protects downstream APIs and manages costs."
                    ),
                },
            ],
            "advanced": [
                {
                    "id": "majority_voting",
                    "name": "Majority Voting Across Agents",
                    "ch12_context": (
                        "Majority Voting Across Agents: For the most critical decisions, a "
                        "panel of agents is used to achieve extreme reliability."
                    ),
                },
                {
                    "id": "trust_decay_and_scoring",
                    "name": "Trust Decay & Scoring",
                    "ch12_context": (
                        "Trust Decay and Scoring: The orchestrator implements a reputation "
                        "system to adaptively route tasks to the most reliable agents."
                    ),
                },
                {
                    "id": "canary_agent_testing",
                    "name": "Canary Agent Testing",
                    "ch12_context": (
                        "Canary Agent Testing: New agent versions are deployed safely into "
                        "production without risking system stability."
                    ),
                },
            ],
        },
    },
    "human_interaction": {
        "name": "Human-Agent Interaction",
        "source_chapter": 8,
        "levels": {
            "basic": [
                {
                    "id": "human_calls_agent",
                    "name": "Human Calls Agent",
                    "ch12_context": (
                        "Human Calls Agent: This is the primary input mechanism for "
                        "transactional, command-based tasks."
                    ),
                },
                {
                    "id": "agent_calls_human",
                    "name": "Agent Calls Human",
                    "ch12_context": (
                        "Agent Calls Human: This is the essential safety valve. The system "
                        "must have a simple, reliable way to stop and escalate to a human "
                        "when it encounters a critical error or low-confidence situation."
                    ),
                },
            ],
            "intermediate": [
                {
                    "id": "agent_delegates_to_agent",
                    "name": "Agent Delegates to Agent",
                    "ch12_context": (
                        "Agent Delegates to Agent: The internal complexity of multi-agent "
                        "collaboration is now abstracted away from the user."
                    ),
                },
                {
                    "id": "agent_calls_proxy_agent",
                    "name": "Agent Calls Proxy Agent",
                    "ch12_context": (
                        "Agent Calls Proxy Agent: Securely manages all interactions with "
                        "external, third-party systems."
                    ),
                },
            ],
            "advanced": [],
        },
    },
    "agent_capabilities": {
        "name": "Agent-Level Capabilities",
        "source_chapter": 9,
        "levels": {
            "basic": [
                {
                    "id": "single_agent_baseline",
                    "name": "Single Agent Baseline",
                    "ch12_context": (
                        "Single Agent Baseline: This defines the structure of your worker "
                        "agents, each equipped with a specific set of tools."
                    ),
                },
                {
                    "id": "agent_specific_memory",
                    "name": "Agent-Specific Memory (Short-Term)",
                    "ch12_context": (
                        "Agent-Specific Memory (Short-Term): At a minimum, agents need a way "
                        "to manage the context of the current session, such as storing the "
                        "conversation history."
                    ),
                },
                {
                    "id": "context_aware_retrieval",
                    "name": "Context-Aware Retrieval (Simple RAG)",
                    "ch12_context": (
                        "Context-Aware Retrieval (Simple RAG): To ground the agent and prevent "
                        "basic hallucinations, connect it to a single, core knowledge source "
                        "via a straightforward RAG pipeline."
                    ),
                },
            ],
            "intermediate": [
                {
                    "id": "advanced_rag",
                    "name": "Advanced RAG",
                    "ch12_context": (
                        "Advanced RAG: The RAG pipeline is enhanced with techniques such as "
                        "re-ranking and query transformation to improve retrieval quality."
                    ),
                },
            ],
            "advanced": [
                {
                    "id": "agentic_rag",
                    "name": "Agentic RAG & Graph-Vector Hybrid Retrieval",
                    "ch12_context": (
                        "Agentic RAG and Graph-Vector Hybrid Retrieval: The system builds and "
                        "maintains its own rich knowledge graph, combining it with vector "
                        "search for state-of-the-art domain expertise."
                    ),
                },
            ],
        },
    },
    "infrastructure": {
        "name": "System-Level Infrastructure",
        "source_chapter": 10,
        "levels": {
            "basic": [
                {
                    "id": "agent_auth_and_authz",
                    "name": "Agent Authentication & Authorization",
                    "ch12_context": (
                        "Agent Authentication and Authorization: Even in a monolithic system, "
                        "if the agent needs to access internal APIs or databases, it must do "
                        "so using a secure service account with clearly defined, least-privilege "
                        "permissions."
                    ),
                },
            ],
            "intermediate": [
                {
                    "id": "tool_and_agent_registry",
                    "name": "Tool & Agent Registry",
                    "ch12_context": (
                        "Tool and Agent Registry: This becomes essential for a microservices "
                        "architecture, allowing agents to dynamically discover each other."
                    ),
                },
                {
                    "id": "event_driven_reactivity",
                    "name": "Event-Driven Reactivity",
                    "ch12_context": (
                        "Event-Driven Reactivity: The entire system is re-architected around "
                        "a central message bus (such as Kafka or Google Cloud Pub/Sub), "
                        "enabling asynchronous, scalable communication."
                    ),
                },
            ],
            "advanced": [],
        },
    },
    "continuous_improvement": {
        "name": "Continuous Improvement",
        "source_chapter": 14,
        "levels": {
            "basic": [],
            "intermediate": [],
            "advanced": [
                {
                    "id": "hybrid_workflow_architecture",
                    "name": "Hybrid Workflow Agent Architecture (Planner + Scorer)",
                    "source_chapter_override": 3,
                    "ch12_context": (
                        "Hybrid Workflow Agent Architecture (Planner + Scorer): The system uses "
                        "a generator-evaluator pairing to create and vet its own workflows."
                    ),
                },
                {
                    "id": "coevolved_agent_training",
                    "name": "Coevolved Agent Training",
                    "ch12_context": (
                        "Coevolved Agent Training: The planner and scorer agents are improved "
                        "in tandem using a mix of SFT, DPO, and iterative learning."
                    ),
                },
                {
                    "id": "preference_controlled_synthetic_data",
                    "name": "Preference-Controlled Synthetic Data Generation",
                    "ch12_context": (
                        "Preference-Controlled Synthetic Data Generation: To prevent runaway "
                        "divergence or collusion, this generation process requires strict "
                        "offline evaluation benchmarks and periodic human-in-the-loop validation."
                    ),
                },
                {
                    "id": "custom_evaluation_metrics",
                    "name": "Custom Evaluation Metrics",
                    "ch12_context": (
                        "Custom Evaluation Metrics: Domain-specific metrics (such as the "
                        "STEPScore) are developed to measure workflow quality accurately."
                    ),
                },
            ],
        },
    },
}


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_chapter_sections_text(chapter_number: int, max_chars: int = 40_000) -> str:
    """Get concatenated section text for a chapter from the DB."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT title, content
        FROM sections
        WHERE chapter_number = ? AND content IS NOT NULL AND content != ''
        ORDER BY line_start
    """, [chapter_number]).fetchall()

    parts = []
    total = 0
    for title, content in rows:
        if total + len(content) > max_chars:
            parts.append(f"--- {title} ---\n{content[:max_chars - total]}")
            break
        parts.append(f"--- {title} ---\n{content}")
        total += len(content)

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Claude extraction
# ---------------------------------------------------------------------------

EXTRACTION_PROMPT = """\
You are analyzing architectural patterns from "Agentic Architectural Patterns \
for Building Multi-Agent Systems" (Arsanjani & Bustos, 2026).

## Pattern to analyze

**Name**: {pattern_name}
**Category**: {category_name}
**Maturity level**: {level}

**Chapter 12 description** (the author's roadmap summary):
{ch12_context}

**Detailed chapter text** (from Chapter {source_chapter}):
{chapter_text}

## Task

Extract 2-5 binary indicators for this pattern that can be verified by \
examining an architecture's source code or design. Each indicator should be:

1. A short, concrete sentence that is either TRUE or FALSE when inspecting code
2. Observable — refers to something you can find in code (function calls, \
config, data structures, control flow) not abstract qualities
3. Grounded in the book's description of this pattern
4. Specific enough that two reviewers would agree on the assessment

Good example indicators:
- "Agent calls are wrapped with an explicit timeout parameter or deadline context"
- "Failed operations are retried with a fixed retry count before giving up"
- "A central orchestrator agent delegates tasks to specialist worker agents"

Bad example indicators (too vague):
- "The system is robust"
- "Error handling is implemented"
- "The architecture follows best practices"

Respond with ONLY a JSON array of indicator strings. Example:
```json
["Indicator one", "Indicator two", "Indicator three"]
```"""


async def extract_indicators_for_pattern(
    pattern: dict,
    category_name: str,
    level: str,
    chapter_text: str,
) -> list[str]:
    """Use Claude to extract binary indicators for a pattern."""
    source_chapter = pattern.get("source_chapter_override", None)

    prompt = EXTRACTION_PROMPT.format(
        pattern_name=pattern["name"],
        category_name=category_name,
        level=level,
        ch12_context=pattern["ch12_context"],
        source_chapter=source_chapter if source_chapter else "see below",
        chapter_text=chapter_text[:30_000],
    )

    # Retry with backoff for rate limits
    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = await claude_messages(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
            )
            break
        except Exception as e:
            if "429" in str(e) and attempt < max_retries - 1:
                wait = 2 ** attempt * 5
                print(f"    Rate limited, waiting {wait}s (attempt {attempt + 1})...")
                await asyncio.sleep(wait)
                continue
            raise

    # Parse JSON
    response = response.strip()
    if response.startswith("```"):
        response = re.sub(r"^```(?:json)?\s*", "", response)
        response = re.sub(r"\s*```$", "", response)

    try:
        indicators = json.loads(response)
        if not isinstance(indicators, list):
            print(f"  WARNING: Expected list, got {type(indicators)}")
            return []
        # Validate: 2-5 non-empty strings
        indicators = [str(i).strip() for i in indicators if str(i).strip()]
        if len(indicators) < 2:
            print(f"  WARNING: Only {len(indicators)} indicators extracted")
        if len(indicators) > 5:
            indicators = indicators[:5]
        return indicators
    except json.JSONDecodeError as e:
        print(f"  ERROR: Failed to parse JSON: {e}")
        print(f"  Response was: {response[:200]}")
        return []


# ---------------------------------------------------------------------------
# Output generation
# ---------------------------------------------------------------------------

def generate_rubric_data(rubric: dict) -> str:
    """Generate the rubric_data.py source code from extracted indicators."""
    lines = [
        '"""',
        "Category-based rubric data extracted from Chapter 12.",
        "",
        "Generated by scripts/extract_indicators.py from:",
        "- Ch. 12 pattern descriptions (roadmap synthesis)",
        "- Source chapter text (detailed pattern definitions)",
        "- Claude-extracted binary indicators",
        "",
        "Do not edit manually — re-run the extraction script to update.",
        '"""',
        "",
        "",
        "# ---------------------------------------------------------------------------",
        "# Rubric: category -> levels -> patterns with indicators",
        "# ---------------------------------------------------------------------------",
        "",
        "RUBRIC: dict[str, dict] = {",
    ]

    all_pattern_ids = []

    for cat_key, cat in rubric.items():
        lines.append(f'    "{cat_key}": {{')
        lines.append(f'        "name": "{cat["name"]}",')
        lines.append(f'        "chapter": {cat["source_chapter"]},')
        lines.append(f'        "levels": {{')

        for level in ("basic", "intermediate", "advanced"):
            patterns = cat["levels"].get(level, [])
            if not patterns:
                lines.append(f'            "{level}": [],')
                continue

            lines.append(f'            "{level}": [')
            for p in patterns:
                all_pattern_ids.append(p["id"])
                lines.append("                {")
                lines.append(f'                    "id": "{p["id"]}",')
                lines.append(f'                    "name": {json.dumps(p["name"])},')
                lines.append(f'                    "indicators": [')
                for ind in p.get("indicators", []):
                    lines.append(f'                        {json.dumps(ind)},')
                lines.append(f'                    ],')
                lines.append("                },")
            lines.append("            ],")

        lines.append("        },")
        lines.append("    },")

    lines.append("}")
    lines.append("")

    # Pattern ID aliases — bridge KG concept IDs to rubric IDs
    lines.append("")
    lines.append("# ---------------------------------------------------------------------------")
    lines.append("# Pattern ID aliases — bridge KG concept IDs to rubric pattern IDs")
    lines.append("# Add entries as needed when KG concept IDs differ from rubric IDs.")
    lines.append("# Format: KG_ID -> RUBRIC_ID (or vice versa)")
    lines.append("# ---------------------------------------------------------------------------")
    lines.append("")
    lines.append("_PATTERN_ID_ALIASES: dict[str, str] = {")
    lines.append('    # Old MATURITY_MODEL IDs -> new rubric IDs')
    lines.append('    "single_agent_baseline_pattern": "single_agent_baseline",')
    lines.append('    "function_calling_pattern": "single_agent_baseline",  # merged into baseline')
    lines.append('    "watchdog_timeout_pattern": "watchdog_timeout",')
    lines.append('    "agent_calls_human_pattern": "agent_calls_human",')
    lines.append('    "agent_router_pattern": "supervisor_architecture",  # subsumed')
    lines.append('    "tool_use_pattern": "single_agent_baseline",  # part of baseline')
    lines.append('    "adaptive_retry_pattern": "simple_retry",')
    lines.append('    "structured_reasoning_and_self": "fractal_cot_embedding",')
    lines.append('    "instruction_fidelity_auditing_pattern": "instruction_fidelity_auditing",')
    lines.append('    "adaptive_retry_with_prompt_mutation": "adaptive_retry_with_prompt_mutation",')
    lines.append('    "supervisor_architecture": "supervisor_architecture",')
    lines.append('    "multi_agent_planning": "multi_agent_planning",')
    lines.append('    "shared_epistemic_memory": "shared_epistemic_memory",')
    lines.append('    "event_driven_reactivity": "event_driven_reactivity",')
    lines.append('    "tool_and_agent_registry": "tool_and_agent_registry",')
    lines.append('    "agent_authentication_and_authorization": "agent_auth_and_authz",')
    lines.append('    "consensus_pattern": "consensus_and_negotiation",')
    lines.append('    "agent_negotiation": "consensus_and_negotiation",')
    lines.append('    "blackboard_knowledge_hub": "shared_epistemic_memory",  # subsumed')
    lines.append('    "self_correction_pattern": "fractal_cot_embedding",')
    lines.append('    "self_improvement_flywheel": "coevolved_agent_training",')
    lines.append('    "custom_evaluation_metrics_pattern": "custom_evaluation_metrics",')
    lines.append('    "coevolved_agent_training_pattern": "coevolved_agent_training",')
    lines.append('    "majority_voting_pattern": "majority_voting",')
    lines.append('    "contract_net_marketplace": "hybrid_delegation_framework",  # subsumed')
    lines.append('    "supervision_tree_with_guarded_capabilities": "supervisor_architecture",  # subsumed')
    lines.append("}")
    lines.append("")

    # Reverse + combined alias maps
    lines.append("# Build reverse map (rubric ID -> old ID, for first occurrence)")
    lines.append("_PATTERN_ID_ALIASES_REVERSE: dict[str, str] = {}")
    lines.append("for _old, _new in _PATTERN_ID_ALIASES.items():")
    lines.append("    if _new not in _PATTERN_ID_ALIASES_REVERSE:")
    lines.append("        _PATTERN_ID_ALIASES_REVERSE[_new] = _old")
    lines.append("")
    lines.append("_PATTERN_ID_ALIAS_COMBINED: dict[str, str] = {")
    lines.append("    **_PATTERN_ID_ALIASES,")
    lines.append("    **_PATTERN_ID_ALIASES_REVERSE,")
    lines.append("}")
    lines.append("")

    # ALL_PATTERN_IDS set
    lines.append("")
    lines.append("# All pattern IDs in the rubric")
    lines.append("ALL_PATTERN_IDS: set[str] = {")
    for pid in sorted(set(all_pattern_ids)):
        lines.append(f'    "{pid}",')
    lines.append("}")
    lines.append("")

    # Helper functions
    lines.append("")
    lines.append("# ---------------------------------------------------------------------------")
    lines.append("# Helpers")
    lines.append("# ---------------------------------------------------------------------------")
    lines.append("")
    lines.append("")
    lines.append("def normalize_pattern_id(pid: str) -> str:")
    lines.append('    """Resolve aliases to canonical rubric ID."""')
    lines.append("    return _PATTERN_ID_ALIASES.get(pid, pid)")
    lines.append("")
    lines.append("")
    lines.append("def get_pattern_indicators(pattern_id: str) -> list[str]:")
    lines.append('    """Return indicators for a pattern, resolving aliases."""')
    lines.append("    pid = normalize_pattern_id(pattern_id)")
    lines.append("    for cat in RUBRIC.values():")
    lines.append('        for level_patterns in cat["levels"].values():')
    lines.append("            for p in level_patterns:")
    lines.append('                if p["id"] == pid:')
    lines.append('                    return p["indicators"]')
    lines.append("    return []")
    lines.append("")
    lines.append("")
    lines.append("def get_pattern_category(pattern_id: str) -> str | None:")
    lines.append('    """Return category key for a pattern, resolving aliases."""')
    lines.append("    pid = normalize_pattern_id(pattern_id)")
    lines.append("    for cat_key, cat in RUBRIC.items():")
    lines.append('        for level_patterns in cat["levels"].values():')
    lines.append("            for p in level_patterns:")
    lines.append('                if p["id"] == pid:')
    lines.append("                    return cat_key")
    lines.append("    return None")
    lines.append("")
    lines.append("")
    lines.append("def get_pattern_level(pattern_id: str) -> str | None:")
    lines.append('    """Return level (basic/intermediate/advanced) for a pattern."""')
    lines.append("    pid = normalize_pattern_id(pattern_id)")
    lines.append("    for cat in RUBRIC.values():")
    lines.append('        for level_name, level_patterns in cat["levels"].items():')
    lines.append("            for p in level_patterns:")
    lines.append('                if p["id"] == pid:')
    lines.append("                    return level_name")
    lines.append("    return None")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    parser = argparse.ArgumentParser(description="Extract rubric indicators from book")
    parser.add_argument("--dry-run", action="store_true", help="Show patterns without calling Claude")
    parser.add_argument("--category", type=str, help="Extract for one category only")
    args = parser.parse_args()

    # Count patterns
    total_patterns = 0
    for cat_key, cat in CH12_RUBRIC.items():
        for level, patterns in cat["levels"].items():
            total_patterns += len(patterns)
    print(f"Rubric: {len(CH12_RUBRIC)} categories, {total_patterns} patterns total")

    if args.dry_run:
        for cat_key, cat in CH12_RUBRIC.items():
            print(f"\n{cat['name']} (ch. {cat['source_chapter']}):")
            for level in ("basic", "intermediate", "advanced"):
                patterns = cat["levels"].get(level, [])
                if patterns:
                    print(f"  {level}:")
                    for p in patterns:
                        print(f"    - {p['name']} ({p['id']})")
                else:
                    print(f"  {level}: (empty)")
        return

    # Cache chapter texts to avoid redundant DB queries
    chapter_texts: dict[int, str] = {}

    categories_to_process = CH12_RUBRIC.items()
    if args.category:
        categories_to_process = [
            (k, v) for k, v in CH12_RUBRIC.items() if k == args.category
        ]
        if not categories_to_process:
            print(f"ERROR: Unknown category '{args.category}'")
            print(f"Available: {', '.join(CH12_RUBRIC.keys())}")
            return

    extracted = 0
    for cat_key, cat in categories_to_process:
        print(f"\n{'='*60}")
        print(f"Category: {cat['name']}")
        print(f"{'='*60}")

        default_chapter = cat["source_chapter"]

        for level in ("basic", "intermediate", "advanced"):
            patterns = cat["levels"].get(level, [])
            if not patterns:
                continue

            print(f"\n  Level: {level}")

            for p in patterns:
                source_ch = p.get("source_chapter_override", default_chapter)

                # Get chapter text (cached)
                if source_ch not in chapter_texts:
                    print(f"  Loading chapter {source_ch} text from DB...")
                    chapter_texts[source_ch] = get_chapter_sections_text(source_ch)
                    if not chapter_texts[source_ch]:
                        print(f"  WARNING: No section text found for chapter {source_ch}")

                print(f"    Extracting: {p['name']}...")
                indicators = await extract_indicators_for_pattern(
                    p, cat["name"], level, chapter_texts[source_ch],
                )

                p["indicators"] = indicators
                extracted += 1
                print(f"    -> {len(indicators)} indicators")

                # Pace requests to avoid rate limits
                await asyncio.sleep(2)
                for i, ind in enumerate(indicators, 1):
                    print(f"       {i}. {ind}")

    print(f"\n{'='*60}")
    print(f"Extracted indicators for {extracted} patterns")

    # Generate output file
    output_path = (
        Path(__file__).resolve().parent.parent
        / "src" / "iconsult_mcp" / "tools" / "rubric_data.py"
    )

    # If --category was used, merge with existing rubric
    if args.category:
        # For single-category extraction, update only that category in CH12_RUBRIC
        # and regenerate the full file
        print(f"\nNote: Only extracted for '{args.category}'. Full rubric written.")

    source = generate_rubric_data(CH12_RUBRIC)
    output_path.write_text(source, encoding="utf-8")
    print(f"\nWritten to: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
