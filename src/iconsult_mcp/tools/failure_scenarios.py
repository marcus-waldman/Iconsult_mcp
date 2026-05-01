"""Generate concrete resilience scenario walkthroughs for patterns not yet in place.

Deterministic — same consultation always produces the same scenarios.
No LLM calls: composes traces from pattern assessments, requires edges,
and book-derived scenario templates.
"""

from iconsult_mcp.db import get_consultation, get_concept_relationships
from iconsult_mcp.tools.rubric_data import RUBRIC, normalize_pattern_id, _PATTERN_ID_ALIAS_COMBINED
from iconsult_mcp.tools.score_architecture import (
    PATTERN_METRICS,
    _get_pattern_assessments,
)

# ---------------------------------------------------------------------------
# Ch. 7 five-step failure recovery chain (p. 206)
# ---------------------------------------------------------------------------

FAILURE_CHAIN: list[dict] = [
    {
        "step": 1,
        "pattern_id": "simple_retry",
        "pattern_name": "Simple Retry",
        "action": "Agent encounters API/LLM call failure",
        "recovery": "Retry with exponential backoff",
        "chapter": 7,
        "page": "214",
    },
    {
        "step": 2,
        "pattern_id": "auto_healing_agent_resuscitation",
        "pattern_name": "Auto-Healing Agent Resuscitation",
        "action": "Retries exhausted, agent process stopped",
        "recovery": "Automatically restart the agent process",
        "chapter": 7,
        "page": "216",
    },
    {
        "step": 3,
        "pattern_id": "fallback_model_invocation",
        "pattern_name": "Fallback Model Invocation",
        "action": "Agent still unsuccessful after restart",
        "recovery": "Switch to fallback model or redundant agent",
        "chapter": 7,
        "page": "238",
    },
    {
        "step": 4,
        "pattern_id": "agent_calls_human",
        "pattern_name": "Delayed Escalation / Agent Calls Human",
        "action": "All automated recovery paths exhausted",
        "recovery": "Escalate to human operator with full context",
        "chapter": 8,
        "page": "251",
    },
    {
        "step": 5,
        "pattern_id": "watchdog_timeout",
        "pattern_name": "Watchdog Timeout Supervisor",
        "action": "Agent becomes unresponsive or enters infinite loop",
        "recovery": "Timeout terminates unresponsive agent, alerts system",
        "chapter": 7,
        "page": "212",
    },
]

# ---------------------------------------------------------------------------
# Per-pattern failure templates — derived from book Problem/Context sections
# ---------------------------------------------------------------------------

PATTERN_FAILURE_TEMPLATES: dict[str, dict] = {
    # Level 1
    "single_agent_baseline_pattern": {
        "trigger": "Core agent logic has no structured task execution",
        "failure_mode": "Output may lack structure, with no tool calling or task completion tracking",
        "cascade": (
            "Agent produces free-form text instead of structured actions → "
            "downstream consumers cannot parse output → pipeline may stall"
        ),
        "book_ref": {"chapter": 9, "page": "309", "section": "Single Agent Baseline"},
    },
    "function_calling_pattern": {
        "trigger": "Agent cannot invoke external tools or APIs",
        "failure_mode": "Agent may generate ungrounded tool results instead of calling APIs",
        "cascade": (
            "Agent generates assumed API response → decisions based on unverified data → "
            "unverified outputs may propagate to downstream agents"
        ),
        "book_ref": {"chapter": 9, "page": "309", "section": "Function Calling"},
    },
    "watchdog_timeout_pattern": {
        "trigger": "External API hangs or agent enters infinite loop",
        "failure_mode": "Agent may block indefinitely without a timeout",
        "cascade": (
            "Agent hangs on API call → orchestrator waits indefinitely → "
            "downstream agents remain idle → pipeline stalls → "
            "user experience degrades, resources consumed without progress"
        ),
        "book_ref": {"chapter": 7, "page": "212", "section": "Watchdog Timeout Supervisor"},
    },
    "agent_calls_human_pattern": {
        "trigger": "Agent encounters ambiguous or high-risk decision",
        "failure_mode": "No defined escalation path to human operator",
        "cascade": (
            "Agent makes autonomous decision on edge case → "
            "action taken without human judgment → "
            "no review step to catch the decision → "
            "potential compliance or financial risk"
        ),
        "book_ref": {"chapter": 8, "page": "251", "section": "Agent Calls Human"},
    },
    # Level 2
    "agent_router_pattern": {
        "trigger": "Incoming request doesn't match any known intent",
        "failure_mode": "No routing logic; all requests go to one agent",
        "cascade": (
            "Specialized request reaches a generalist agent → agent lacks domain knowledge → "
            "lower quality response → user retries → repeated attempts needed"
        ),
        "book_ref": {"chapter": 5, "page": "142", "section": "Agent Router"},
    },
    "tool_use_pattern": {
        "trigger": "Agent needs to select from multiple available tools",
        "failure_mode": "Hardcoded tool selection, no dynamic dispatch",
        "cascade": (
            "New tool added but agent can't discover it → "
            "misses optimal tool for task → suboptimal results"
        ),
        "book_ref": {"chapter": 9, "page": "309", "section": "Dynamic Tool Selection"},
    },
    "adaptive_retry_pattern": {
        "trigger": "Transient API failure (503, timeout, rate limit)",
        "failure_mode": "Single transient failure can stop the entire pipeline",
        "cascade": (
            "API returns 503 → no retry logic → exception propagates → "
            "orchestrator receives unhandled error → pipeline stops → "
            "user sees error, task requires manual restart"
        ),
        "book_ref": {"chapter": 7, "page": "214", "section": "Adaptive Retry"},
    },
    # Level 3
    "structured_reasoning_and_self": {
        "trigger": "Agent produces incorrect reasoning on first attempt",
        "failure_mode": "No self-critique or reflection loop",
        "cascade": (
            "Agent generates initial analysis → no verification step → "
            "unreviewed output passed as final → downstream decisions rely on unverified results"
        ),
        "book_ref": {"chapter": 9, "page": "309", "section": "Structured Reasoning"},
    },
    "instruction_fidelity_auditing_pattern": {
        "trigger": "Agent deviates from system instructions or policy",
        "failure_mode": "No audit trail of instruction adherence",
        "cascade": (
            "Agent drifts from safety guardrails → produces non-compliant output → "
            "drift goes undetected until production review → "
            "potential regulatory or reputational risk"
        ),
        "book_ref": {"chapter": 6, "page": "177", "section": "Instruction Fidelity Auditing"},
    },
    "adaptive_retry_with_prompt_mutation": {
        "trigger": "Agent fails deterministically on same input",
        "failure_mode": "Simple retry repeats the same unsuccessful prompt",
        "cascade": (
            "Prompt misinterpretation causes wrong output → retry sends same prompt → "
            "same output repeated N times → retries exhausted → "
            "task cannot complete without prompt adjustment"
        ),
        "book_ref": {"chapter": 7, "page": "214", "section": "Adaptive Retry with Prompt Mutation"},
    },
    # Level 4
    "supervisor_architecture": {
        "trigger": "Multiple agents need coordination for complex task",
        "failure_mode": "No central supervisor; agents operate independently",
        "cascade": (
            "Agents produce differing outputs → no arbitration mechanism → "
            "results merged without reconciliation → potentially contradictory final output"
        ),
        "book_ref": {"chapter": 5, "page": "142", "section": "Supervisor Architecture"},
    },
    "multi_agent_planning": {
        "trigger": "Complex task requires decomposition into subtasks",
        "failure_mode": "No planning phase; agents given full task directly",
        "cascade": (
            "Agent receives full task complexity at once → produces shallow output → "
            "subtasks may be overlooked → incomplete result"
        ),
        "book_ref": {"chapter": 5, "page": "142", "section": "Multi-Agent Planning"},
    },
    "shared_epistemic_memory": {
        "trigger": "Agent B needs context from Agent A's earlier work",
        "failure_mode": "No shared memory; each agent starts from scratch",
        "cascade": (
            "Agent B repeats Agent A's work → duplicated effort and token usage → "
            "potential inconsistencies between agents → output may lack coherence"
        ),
        "book_ref": {"chapter": 5, "page": "142", "section": "Shared Epistemic Memory"},
    },
    "event_driven_reactivity": {
        "trigger": "System state changes that require immediate response",
        "failure_mode": "Polling-only or no event system",
        "cascade": (
            "Important system event occurs → "
            "no event bus to propagate signal → agents continue normal operation → "
            "delayed awareness and response"
        ),
        "book_ref": {"chapter": 10, "page": "314", "section": "Event-Driven Reactivity"},
    },
    "tool_and_agent_registry": {
        "trigger": "New agent or tool added to the system",
        "failure_mode": "Hardcoded agent/tool references throughout",
        "cascade": (
            "New capability added but not discoverable → "
            "orchestrator can't route to it → capability unused → "
            "manual config changes needed for every addition"
        ),
        "book_ref": {"chapter": 10, "page": "311", "section": "Tool and Agent Registry"},
    },
    "agent_authentication_and_authorization": {
        "trigger": "Agent accesses sensitive data or external API",
        "failure_mode": "No auth layer; all agents have equal access",
        "cascade": (
            "Agent with a defect accesses all resources → "
            "potential data exposure or unauthorized action → no audit trail of access → "
            "limited forensics if an incident occurs"
        ),
        "book_ref": {"chapter": 10, "page": "311", "section": "Agent Authentication & Authorization"},
    },
    # Level 5
    "contract_net_marketplace": {
        "trigger": "Task needs competitive bidding among agents",
        "failure_mode": "Static task assignment, no dynamic allocation",
        "cascade": (
            "Best-suited agent overloaded while others idle → "
            "suboptimal resource utilization → slower response times"
        ),
        "book_ref": {"chapter": 5, "page": "142", "section": "Contract-Net Marketplace"},
    },
    "supervision_tree_with_guarded_capabilities": {
        "trigger": "Sub-agent crashes and needs restart with capability constraints",
        "failure_mode": "Flat agent topology, no supervision hierarchy",
        "cascade": (
            "Agent issue propagates upward → no isolation boundary → "
            "parent affected → cascading impact across the system"
        ),
        "book_ref": {"chapter": 5, "page": "142", "section": "Supervision Tree"},
    },
    "agent_negotiation": {
        "trigger": "Agents have conflicting goals or resource constraints",
        "failure_mode": "No negotiation protocol; first-come-first-served",
        "cascade": (
            "Agents compete for shared resource → potential deadlock or resource contention → "
            "lower-priority but important task delayed indefinitely"
        ),
        "book_ref": {"chapter": 5, "page": "142", "section": "Agent Negotiation"},
    },
    "consensus_pattern": {
        "trigger": "Multiple agents must agree on a shared decision",
        "failure_mode": "Single agent decides unilaterally",
        "cascade": (
            "Single agent's perspective goes unchecked → "
            "no second opinion → decision propagated without validation"
        ),
        "book_ref": {"chapter": 5, "page": "142", "section": "Consensus Pattern"},
    },
    "blackboard_knowledge_hub": {
        "trigger": "Agents need shared workspace for incremental problem-solving",
        "failure_mode": "No shared data structure; agents pass messages only",
        "cascade": (
            "Intermediate results lost between agent turns → "
            "agents repeat work → no incremental progress tracking"
        ),
        "book_ref": {"chapter": 5, "page": "142", "section": "Blackboard Knowledge Hub"},
    },
    # Level 6
    "self_correction_pattern": {
        "trigger": "Agent detects its own output quality degradation",
        "failure_mode": "No self-monitoring or correction capability",
        "cascade": (
            "Quality drifts over time → no detection mechanism → "
            "users notice changes before system does → trust may decline"
        ),
        "book_ref": {"chapter": 9, "page": "309", "section": "Self-Correction"},
    },
    "self_improvement_flywheel": {
        "trigger": "System should learn from past successes and failures",
        "failure_mode": "No feedback loop; same mistakes repeated",
        "cascade": (
            "Recurring issue pattern → no learning mechanism → "
            "same situation arises in production repeatedly → manual intervention each time"
        ),
        "book_ref": {"chapter": 11, "page": "367", "section": "Self-Improvement Flywheel"},
    },
    "custom_evaluation_metrics_pattern": {
        "trigger": "Need domain-specific quality measurement",
        "failure_mode": "Only generic metrics (latency, token count)",
        "cascade": (
            "Domain-critical quality issues missed by generic metrics → "
            "system reports 'healthy' while output quality is poor → "
            "silent degradation"
        ),
        "book_ref": {"chapter": 11, "page": "367", "section": "Custom Evaluation Metrics"},
    },
    "coevolved_agent_training_pattern": {
        "trigger": "Agent ecosystem needs coordinated capability upgrades",
        "failure_mode": "Agents updated independently without compatibility testing",
        "cascade": (
            "Agent A upgraded but Agent B expects old interface → "
            "integration issue at runtime → cascading impact across agents"
        ),
        "book_ref": {"chapter": 14, "page": "497", "section": "Coevolved Agent Training"},
    },
    "majority_voting_pattern": {
        "trigger": "Critical decision needs validation from multiple agents",
        "failure_mode": "Single agent's output accepted without verification",
        "cascade": (
            "Agent produces a result → no cross-validation → "
            "output accepted without verification → decision proceeds unvalidated"
        ),
        "book_ref": {"chapter": 7, "page": "207", "section": "Majority Voting Across Agents"},
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_all_model_pattern_ids() -> set[str]:
    """All pattern IDs in RUBRIC."""
    ids = set()
    for cat in RUBRIC.values():
        for level_patterns in cat["levels"].values():
            for p in level_patterns:
                ids.add(p["id"])
    return ids


# Level priority for severity computation (basic=1, intermediate=2, advanced=3)
_LEVEL_PRIORITY = {"basic": 1, "intermediate": 2, "advanced": 3}


def _get_pattern_level(pattern_id: str) -> int | None:
    """Look up the maturity level for a pattern ID (1=basic, 2=intermediate, 3=advanced)."""
    pid = normalize_pattern_id(pattern_id)
    for cat in RUBRIC.values():
        for level_name, level_patterns in cat["levels"].items():
            for p in level_patterns:
                if p["id"] == pid:
                    return _LEVEL_PRIORITY.get(level_name)
    return None


def _find_dependent_patterns(
    pattern_id: str,
    assessments: dict[str, dict],
) -> list[dict]:
    """Find patterns that require the given pattern (via 'requires' edges).

    Returns patterns that are implemented/partial but depend on a missing one.
    """
    dependents = []
    try:
        rels = get_concept_relationships(pattern_id, confidence_threshold=0.3)
    except Exception:
        return dependents

    for rel in rels:
        if rel["relationship_type"] != "requires":
            continue
        # requires edge: from requires to. If our pattern is the target (to),
        # then from_concept_id depends on us.
        if rel["to_concept_id"] == pattern_id:
            dep_id = rel["from_concept_id"]
            dep_assessment = assessments.get(dep_id)
            if dep_assessment and dep_assessment.get("status") in ("implemented", "partial"):
                dependents.append({
                    "pattern_id": dep_id,
                    "pattern_name": rel["from_name"],
                    "status": dep_assessment["status"],
                    "relationship": "requires",
                })
    return dependents


def _build_cascade_steps(
    pattern_id: str,
    template: dict,
    assessment: dict | None,
) -> list[dict]:
    """Build cascade steps for a failure scenario.

    Uses code references from failure_context if available,
    otherwise uses book-grounded template.
    """
    steps = []
    step_num = 0

    # Check for code-grounded evidence
    failure_context = assessment.get("failure_context", {}) if assessment else {}
    code_refs = failure_context.get("code_refs", [])

    # Parse the cascade string into steps
    cascade_parts = template["cascade"].split(" → ")

    for i, part in enumerate(cascade_parts):
        step_num += 1
        step = {
            "step": step_num,
            "description": part.strip(),
            "code_ref": None,
            "outcome": "failure_propagates" if i < len(cascade_parts) - 1 else "system_impact",
        }

        # Attach code reference if available for this step
        if i < len(code_refs):
            ref = code_refs[i]
            step["code_ref"] = f"{ref.get('file', '?')}:{ref.get('line', '?')}"
            if ref.get("snippet"):
                step["snippet"] = ref["snippet"]

        steps.append(step)

    return steps


def _compute_severity(
    pattern_id: str,
    dependents: list[dict],
    level: int | None,
) -> str:
    """Compute scenario severity based on dependencies and pattern importance."""
    # Security/compliance patterns are always CRITICAL
    if pattern_id in (
        "instruction_fidelity_auditing",
        "agent_auth_and_authz",
    ):
        return "CRITICAL"

    # Patterns with implemented dependents (inverted pyramid) are CRITICAL
    if dependents:
        return "CRITICAL"

    # L1 foundational patterns are CRITICAL
    if level == 1:
        return "CRITICAL"

    # L2 patterns are WARNING
    if level == 2:
        return "WARNING"

    return "INFO"


def _build_failure_chain_coverage(
    assessments: dict[str, dict],
) -> dict:
    """Map the Ch. 7 five-step failure chain against pattern assessments."""
    chain_steps = []
    implemented_count = 0

    for link in FAILURE_CHAIN:
        pid = link["pattern_id"]
        assessment = assessments.get(pid)
        if not assessment:
            # Try alias
            alias = _PATTERN_ID_ALIAS_COMBINED.get(pid)
            if alias:
                assessment = assessments.get(alias)
        status = assessment["status"] if assessment else "not_assessed"

        is_covered = status in ("implemented", "partial")
        if is_covered:
            implemented_count += 1

        chain_steps.append({
            "step": link["step"],
            "pattern_name": link["pattern_name"],
            "pattern_id": pid,
            "action": link["action"],
            "recovery": link["recovery"],
            "status": status,
            "gap": not is_covered,
            "chapter": link["chapter"],
            "page": link["page"],
        })

    total = len(FAILURE_CHAIN)
    coverage_pct = int((implemented_count / total) * 100) if total > 0 else 0

    # Find first gap
    first_gap = None
    for s in chain_steps:
        if s["gap"]:
            first_gap = f"Step {s['step']}: {s['pattern_name']}"
            break

    return {
        "steps": chain_steps,
        "chain_coverage": f"{coverage_pct}%",
        "implemented": implemented_count,
        "total": total,
        "first_gap": first_gap,
    }


# ---------------------------------------------------------------------------
# Main tool
# ---------------------------------------------------------------------------

async def generate_failure_scenarios(
    consultation_id: str,
    max_scenarios: int = 5,
) -> dict:
    """Generate concrete resilience scenario walkthroughs for patterns not yet in place.

    Each scenario illustrates how the architecture would respond under stress: trigger
    event, step-by-step propagation (with file:line references when code evidence is
    available), and potential impact. Also maps coverage against Ch. 7's five-step
    failure chain.

    Deterministic — same consultation always produces the same scenarios.

    Args:
        consultation_id: The consultation session to analyze.
        max_scenarios: Maximum number of scenarios to return (default: 5).
    """
    if not consultation_id or not consultation_id.strip():
        return {"error": "consultation_id is required"}

    record = get_consultation(consultation_id)
    if not record:
        return {"error": f"Consultation '{consultation_id}' not found"}

    assessments = _get_pattern_assessments(record)
    if not assessments:
        return {
            "error": "No pattern assessments found. Run graph traversal (step 3) "
            "with log_pattern_assessment before generating failure scenarios.",
            "consultation_id": consultation_id,
        }

    # Build scenarios for missing/partial patterns
    scenarios = []

    for cat_key, cat in RUBRIC.items():
        for level_name, level_patterns in cat["levels"].items():
            for pattern in level_patterns:
                pid = pattern["id"]
                assessment = assessments.get(pid)
                status = assessment["status"] if assessment else "not_assessed"

                # Only build scenarios for missing/partial patterns
                if status not in ("missing", "partial"):
                    continue

                template = PATTERN_FAILURE_TEMPLATES.get(pid)
                if not template:
                    # Try alias (templates may use old MATURITY_MODEL IDs)
                    alias = _PATTERN_ID_ALIAS_COMBINED.get(pid)
                    if alias:
                        template = PATTERN_FAILURE_TEMPLATES.get(alias)
                if not template:
                    continue

                # Find implemented patterns that depend on this missing one
                dependents = _find_dependent_patterns(pid, assessments)

                # Determine mode
                failure_context = assessment.get("failure_context", {}) if assessment else {}
                has_code = bool(failure_context.get("code_refs"))
                mode = "code_grounded" if has_code else "book_grounded"

                # Build cascade steps
                cascade_steps = _build_cascade_steps(pid, template, assessment)

                # Severity
                level_num = _LEVEL_PRIORITY.get(level_name, 2)
                severity = _compute_severity(pid, dependents, level_num)

                # Phase 5b: source-book attribution. When the user-logged
                # assessment carries source_book_id, that's the answer
                # ("we looked in gulli_2025 for this pattern and didn't
                # find it in the project"). Otherwise default to
                # arsanjani_2026 — every entry in PATTERN_FAILURE_TEMPLATES
                # comes from arsanjani Ch. 7-12, so book-grounded scenarios
                # are arsanjani-sourced by construction. The rubric IS
                # Ch. 12. Emitted on every scenario so the report can
                # render a consistent badge per row regardless of mode.
                sbid = (
                    assessment.get("source_book_id") if assessment else None
                ) or "arsanjani_2026"

                # Build the scenario
                scenario = {
                    "scenario_id": len(scenarios) + 1,
                    "title": f"{'Without ' if status == 'missing' else 'Strengthening '}{pattern['name']} → {template['trigger']}",
                    "trigger": template["trigger"],
                    "missing_pattern": {
                        "id": pid,
                        "name": pattern["name"],
                        "status": status,
                        "category": cat_key,
                        "level": level_name,
                        "chapter": cat["chapter"],
                    },
                    "severity": severity,
                    "cascade_steps": cascade_steps,
                    "book_reference": template["book_ref"],
                    "mode": mode,
                    "source_book_id": sbid,
                }

                # Add recovery recommendation
                metric = PATTERN_METRICS.get(pid)
                if metric:
                    scenario["recovery"] = (
                        f"Implement {pattern['name']} "
                        f"(target: {metric['metric']}; {metric['source']})"
                    )
                else:
                    scenario["recovery"] = (
                        f"Implement {pattern['name']} "
                        f"(Ch. {cat['chapter']})"
                    )

                # Add evidence from assessment
                if assessment and assessment.get("evidence"):
                    scenario["evidence"] = assessment["evidence"]

                # Add failure_context details if present
                if failure_context.get("failure_mode"):
                    scenario["failure_mode_detail"] = failure_context["failure_mode"]

                # Flag inverted pyramid: advanced pattern depends on this missing foundation
                if dependents:
                    scenario["inverted_pyramid"] = {
                        "warning": (
                            f"{pattern['name']} ({level_name}) is not yet in place — "
                            f"these higher-level patterns would benefit from it as a foundation"
                        ),
                        "affected_patterns": dependents,
                    }

                scenarios.append(scenario)

    # Sort: CRITICAL first, then WARNING, then INFO; within same severity, basic first
    severity_order = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
    level_order = {"basic": 0, "intermediate": 1, "advanced": 2}
    scenarios.sort(key=lambda s: (
        severity_order.get(s["severity"], 3),
        level_order.get(s["missing_pattern"].get("level", ""), 9),
    ))

    # Truncate
    scenarios = scenarios[:max_scenarios]

    # Re-number after sort and truncate
    for i, s in enumerate(scenarios):
        s["scenario_id"] = i + 1

    # Failure chain coverage
    failure_chain = _build_failure_chain_coverage(assessments)

    # Summary stats
    missing_count = sum(
        1 for a in assessments.values() if a.get("status") == "missing"
    )
    partial_count = sum(
        1 for a in assessments.values() if a.get("status") == "partial"
    )
    inverted_count = sum(
        1 for s in scenarios if "inverted_pyramid" in s
    )

    return {
        "consultation_id": consultation_id,
        "scenario_count": len(scenarios),
        "scenarios": scenarios,
        "failure_chain": failure_chain,
        "summary": {
            "total_missing": missing_count,
            "total_partial": partial_count,
            "scenarios_generated": len(scenarios),
            "inverted_pyramid_warnings": inverted_count,
            "chain_coverage": failure_chain["chain_coverage"],
        },
    }
