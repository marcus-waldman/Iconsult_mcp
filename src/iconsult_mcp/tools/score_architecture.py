"""Deterministic architecture scoring from stored pattern assessments.

Reads pattern_assessment steps logged during graph traversal and computes
scores using fixed formulas. Same consultation always produces same scores.
"""

from iconsult_mcp.db import get_consultation, get_concept_relationships

# ---------------------------------------------------------------------------
# Scoring model constants — derived from book tables
# Ch. 3 (Agentic AI Maturity), Ch. 5 (Table 5.3), Ch. 7 (Table 7.2),
# Ch. 8 (Table 8.2), Ch. 9 (Table 9.3), Ch. 10 (Table 10.1)
# ---------------------------------------------------------------------------

# Patterns required at each maturity level.
# A system is "at" a level if all patterns for that level AND below are
# implemented (or partial).
MATURITY_MODEL: dict[int, list[dict]] = {
    1: [
        {"id": "single_agent_baseline_pattern", "name": "Single Agent Baseline", "chapter": 9},
        {"id": "function_calling_pattern", "name": "Function Calling", "chapter": 9},
        {"id": "watchdog_timeout_pattern", "name": "Watchdog Timeout", "chapter": 7},
        {"id": "agent_calls_human_pattern", "name": "Agent Calls Human", "chapter": 8},
    ],
    2: [
        {"id": "agent_router_pattern", "name": "Agent Router", "chapter": 5},
        {"id": "tool_use_pattern", "name": "Dynamic Tool Selection", "chapter": 9},
        {"id": "adaptive_retry_pattern", "name": "Simple Retry", "chapter": 7},
    ],
    3: [
        {"id": "structured_reasoning_and_self", "name": "ReAct / Reflexion", "chapter": 9},
        {"id": "instruction_fidelity_auditing_pattern", "name": "Instruction Fidelity Auditing", "chapter": 6},
        {"id": "adaptive_retry_with_prompt_mutation", "name": "Adaptive Retry with Prompt Mutation", "chapter": 7},
    ],
    4: [
        {"id": "supervisor_architecture", "name": "Supervisor Architecture", "chapter": 5},
        {"id": "multi_agent_planning", "name": "Multi-Agent Planning", "chapter": 5},
        {"id": "shared_epistemic_memory", "name": "Shared Epistemic Memory", "chapter": 5},
        {"id": "event_driven_reactivity", "name": "Event-Driven Reactivity", "chapter": 10},
        {"id": "tool_and_agent_registry", "name": "Tool / Agent Registry", "chapter": 10},
        {"id": "agent_authentication_and_authorization", "name": "Agent Authentication & Authorization", "chapter": 10},
    ],
    5: [
        {"id": "contract_net_marketplace", "name": "Contract-Net Marketplace", "chapter": 5},
        {"id": "supervision_tree_with_guarded_capabilities", "name": "Supervision Tree", "chapter": 5},
        {"id": "agent_negotiation", "name": "Agent Negotiation", "chapter": 5},
        {"id": "consensus_pattern", "name": "Consensus", "chapter": 5},
        {"id": "blackboard_knowledge_hub", "name": "Blackboard Knowledge Hub", "chapter": 5},
    ],
    6: [
        {"id": "self_correction_pattern", "name": "Self-Correction", "chapter": 9},
        {"id": "self_improvement_flywheel", "name": "Self-Improvement Flywheel", "chapter": 11},
        {"id": "custom_evaluation_metrics_pattern", "name": "Custom Evaluation Metrics", "chapter": 11},
        {"id": "coevolved_agent_training_pattern", "name": "Coevolved Agent Training", "chapter": 14},
        {"id": "majority_voting_pattern", "name": "Majority Voting Across Agents", "chapter": 7},
    ],
}

# Per-pattern recommended metrics from Ch. 7 (Table 7.2), Ch. 8 (Table 8.2),
# Ch. 9 (Table 9.3). Only patterns with book-defined metrics are included.
PATTERN_METRICS: dict[str, dict] = {
    # Ch. 9 — Agent-level
    "single_agent_baseline_pattern": {
        "metric": "Task completion rate / tool call success rate",
        "instrumentation": "Log final outcome of each task (success/failure). Monitor failed tool API calls.",
        "source": "Ch. 9, Table 9.3",
    },
    "agent_specific_context_and_memory": {
        "metric": "Session coherence score / reduction in repeated questions",
        "instrumentation": "Human raters score conversation quality. Track repeated information requests.",
        "source": "Ch. 9, Table 9.3",
    },
    "structured_reasoning_and_self": {
        "metric": "Self-correction trigger rate / reduction in final errors",
        "instrumentation": "Track how often critique step identifies a flaw. Compare preliminary vs final error rate.",
        "source": "Ch. 9, Table 9.3",
    },
    "multimodal_sensory_input_pattern": {
        "metric": "Data extraction accuracy / success on visual tasks",
        "instrumentation": "Measure OCR/field extraction accuracy against ground-truth data.",
        "source": "Ch. 9, Table 9.3",
    },
    # Ch. 7 — Robustness
    "adaptive_retry_pattern": {
        "metric": "Recovery rate (%)",
        "instrumentation": "Count successful retries versus initial failures.",
        "source": "Ch. 7, Table 7.2",
    },
    "watchdog_timeout_pattern": {
        "metric": "P99 latency & violation rate",
        "instrumentation": "99th percentile response time; timeout violations per hour.",
        "source": "Ch. 7, Table 7.2",
    },
    "auto_healing_pattern": {
        "metric": "Resuscitation success rate (%)",
        "instrumentation": "Logs of successful agent restarts after a crash.",
        "source": "Ch. 7, Table 7.2",
    },
    "trust_decay_pattern": {
        "metric": "Agent reliability trend",
        "instrumentation": "Rolling performance window (success/failure rate) for each agent.",
        "source": "Ch. 7, Table 7.2",
    },
    "fallback_model_invocation_pattern": {
        "metric": "Accuracy delta (%)",
        "instrumentation": "Compare fallback vs primary model output accuracy on golden dataset.",
        "source": "Ch. 7, Table 7.2",
    },
    "majority_voting_pattern": {
        "metric": "Conflict rate (%)",
        "instrumentation": "Percentage of tasks requiring escalation due to lack of majority consensus.",
        "source": "Ch. 7, Table 7.2",
    },
    "canary_agent_testing_pattern": {
        "metric": "Regression rate (%)",
        "instrumentation": "Percentage of canary outputs showing negative drift from stable version.",
        "source": "Ch. 7, Table 7.2",
    },
    # Ch. 8 — Human-Agent Interaction
    "agent_calls_human_pattern": {
        "metric": "Escalation rate / resolution time",
        "instrumentation": "Log every escalation event. Measure time from escalation to human response.",
        "source": "Ch. 8, Table 8.2",
    },
    "human_delegates_to_agent": {
        "metric": "Task success rate / user satisfaction (CSAT/NPS)",
        "instrumentation": "Track end-to-end completion rate. Follow up with user survey.",
        "source": "Ch. 8, Table 8.2",
    },
    "human_calls_agent_pattern": {
        "metric": "First-contact resolution rate / average response time",
        "instrumentation": "Percentage of queries solved in single turn. End-to-end latency.",
        "source": "Ch. 8, Table 8.2",
    },
    "agent_delegates_to_agent_pattern": {
        "metric": "Orchestration overhead / sub-task failure rate",
        "instrumentation": "Log timestamps for each inter-agent delegation. Track specialist agent errors.",
        "source": "Ch. 8, Table 8.2",
    },
    "agent_calls_proxy_agent_pattern": {
        "metric": "External API error rate / security incidents",
        "instrumentation": "Monitor proxy agent logs for failed/timed-out API calls.",
        "source": "Ch. 8, Table 8.2",
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_pattern_assessments(record: dict) -> dict[str, dict]:
    """Extract pattern assessments from consultation steps, keyed by pattern_id."""
    assessments = {}
    for step in record.get("steps", []):
        if step.get("type") == "pattern_assessment":
            pid = step.get("pattern_id")
            if pid:
                assessments[pid] = step
    return assessments


def _all_pattern_ids() -> set[str]:
    """All unique pattern IDs referenced in MATURITY_MODEL."""
    ids = set()
    for patterns in MATURITY_MODEL.values():
        for p in patterns:
            ids.add(p["id"])
    return ids


def _compute_maturity_level(assessments: dict[str, dict]) -> dict:
    """Determine current maturity level based on pattern implementation."""
    current_level = 0
    level_details = {}

    for level in sorted(MATURITY_MODEL.keys()):
        patterns = MATURITY_MODEL[level]
        statuses = []
        for p in patterns:
            a = assessments.get(p["id"])
            status = a["status"] if a else "missing"
            statuses.append({"id": p["id"], "name": p["name"], "status": status})

        all_met = all(s["status"] in ("implemented", "partial") for s in statuses)
        level_details[level] = {
            "patterns": statuses,
            "met": all_met,
        }
        if all_met:
            current_level = level

    return {"current_level": current_level, "level_details": level_details}


def _compute_pattern_coverage(assessments: dict[str, dict], target_level: int) -> list[dict]:
    """Build full pattern coverage table across all maturity levels with goals."""
    coverage = []
    for level in sorted(MATURITY_MODEL.keys()):
        for p in MATURITY_MODEL[level]:
            a = assessments.get(p["id"])
            status = a["status"] if a else "missing"
            # Goal: if already implemented, stays implemented.
            # If missing/partial and at or below target level, goal is "implemented".
            # Otherwise goal stays as current status (not targeted yet).
            if status == "implemented":
                goal = "implemented"
            elif level <= target_level:
                goal = "implemented"
            else:
                goal = status
            priority = "HIGH" if status in ("missing", "partial") else "---"
            coverage.append({
                "pattern_id": p["id"],
                "pattern_name": p["name"],
                "status": status,
                "goal": goal,
                "maturity_level": level,
                "chapter": p["chapter"],
                "priority": priority,
                "evidence": a.get("evidence", "") if a else "",
            })
    return coverage


def _compute_gap_analysis(
    assessments: dict[str, dict],
    current_level: int,
    target_level: int,
) -> list[dict]:
    """Identify gaps with severity based on prerequisite/conflict edges."""
    gaps = []

    for level in range(current_level + 1, target_level + 1):
        for p in MATURITY_MODEL.get(level, []):
            a = assessments.get(p["id"])
            status = a["status"] if a else "missing"
            if status == "implemented":
                continue

            # Check if this pattern has requires/conflicts_with edges
            severity = "WARNING"
            try:
                rels = get_concept_relationships(p["id"], confidence_threshold=0.3)
                has_prereq = any(r["relationship_type"] == "requires" for r in rels)
                has_conflict = any(r["relationship_type"] == "conflicts_with" for r in rels)
                if has_prereq or has_conflict:
                    severity = "CRITICAL"
            except Exception:
                pass

            # Assign CRITICAL to compliance/security patterns regardless
            if p["id"] in (
                "instruction_fidelity_auditing_pattern",
                "agent_authentication_and_authorization",
                "execution_envelope_isolation",
            ):
                severity = "CRITICAL"

            gaps.append({
                "pattern_id": p["id"],
                "pattern_name": p["name"],
                "status": status,
                "maturity_level": level,
                "severity": severity,
                "chapter": p["chapter"],
            })

    return gaps


def _compute_recommended_metrics(gaps: list[dict], assessments: dict[str, dict]) -> list[dict]:
    """Return book-defined metrics for missing/partial patterns."""
    metrics = []
    seen = set()
    # Include metrics for gap patterns
    for gap in gaps:
        pid = gap["pattern_id"]
        if pid in PATTERN_METRICS and pid not in seen:
            seen.add(pid)
            m = PATTERN_METRICS[pid]
            metrics.append({
                "pattern_id": pid,
                "pattern_name": gap["pattern_name"],
                "metric": m["metric"],
                "instrumentation": m["instrumentation"],
                "source": m["source"],
                "current": "N/A",
            })
    # Include metrics for partial patterns not in gaps
    for pid, a in assessments.items():
        if a.get("status") == "partial" and pid in PATTERN_METRICS and pid not in seen:
            seen.add(pid)
            m = PATTERN_METRICS[pid]
            metrics.append({
                "pattern_id": pid,
                "pattern_name": a.get("pattern_name", pid),
                "metric": m["metric"],
                "instrumentation": m["instrumentation"],
                "source": m["source"],
                "current": "Partial",
            })
    return metrics


def _compute_roadmap(gaps: list[dict], current_level: int, target_level: int) -> list[dict]:
    """Group gaps into implementation phases by maturity level."""
    phases = []
    for level in range(current_level + 1, target_level + 1):
        level_gaps = [g for g in gaps if g["maturity_level"] == level]
        if not level_gaps:
            continue
        phases.append({
            "phase": len(phases) + 1,
            "target_level": level,
            "patterns": [
                {"name": g["pattern_name"], "status": g["status"], "severity": g["severity"]}
                for g in level_gaps
            ],
        })
    return phases


# ---------------------------------------------------------------------------
# Main tool
# ---------------------------------------------------------------------------

async def score_architecture(
    consultation_id: str,
    target_level: int | None = None,
) -> dict:
    """Compute deterministic architecture maturity scores from stored assessments.

    Args:
        consultation_id: The consultation session to score.
        target_level: Override auto-detected target level (1-6).
    """
    record = get_consultation(consultation_id)
    if not record:
        return {"error": f"Consultation '{consultation_id}' not found"}

    assessments = _get_pattern_assessments(record)
    if not assessments:
        return {
            "error": "No pattern assessments found in this consultation. "
            "During graph traversal (step 3), log pattern_assessment steps "
            "for each pattern found in the user's codebase.",
            "consultation_id": consultation_id,
            "hint": "Use log_consultation_step(consultation_id, 'pattern_assessment', "
            "{pattern_id, pattern_name, status, evidence, maturity_level})",
        }

    # Compute maturity
    maturity = _compute_maturity_level(assessments)
    current_level = maturity["current_level"]

    # Auto-detect target: next level up, capped at 6
    if target_level is None:
        target_level = min(current_level + 1, 6)
    target_level = max(1, min(6, target_level))

    # Compute all sections
    pattern_coverage = _compute_pattern_coverage(assessments, target_level)
    gaps = _compute_gap_analysis(assessments, current_level, target_level)
    recommended_metrics = _compute_recommended_metrics(gaps, assessments)
    roadmap = _compute_roadmap(gaps, current_level, target_level)

    # Summary stats
    total_assessed = len(assessments)
    total_patterns = len(_all_pattern_ids())
    implemented = sum(1 for a in assessments.values() if a.get("status") == "implemented")
    partial = sum(1 for a in assessments.values() if a.get("status") == "partial")
    missing = sum(1 for a in assessments.values() if a.get("status") == "missing")

    return {
        "consultation_id": consultation_id,
        "scoring_method": "deterministic — fixed formulas applied to stored pattern assessments",
        "maturity": {
            "current_level": current_level,
            "target_level": target_level,
            "level_details": maturity["level_details"],
        },
        "pattern_coverage": {
            "total_assessed": total_assessed,
            "total_patterns_in_model": total_patterns,
            "implemented": implemented,
            "partial": partial,
            "missing": missing,
            "details": pattern_coverage,
        },
        "gap_analysis": gaps,
        "recommended_metrics": recommended_metrics,
        "roadmap": roadmap,
    }
