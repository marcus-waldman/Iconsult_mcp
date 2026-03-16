"""Supervisor architecture for consultation workflow.

Tracks progress through the consultation workflow and suggests the next action.
Called repeatedly by the orchestrator after each major step.
"""

from iconsult_mcp.db import (
    get_consultation,
    get_consultation_events,
    read_shared_state,
)

# Ordered workflow phases with their step types and labels
WORKFLOW_PHASES = [
    {"phase": "match", "step_types": ["match"], "label": "Match Concepts"},
    {"phase": "plan", "step_types": ["plan_created"], "label": "Plan Consultation"},
    {"phase": "traverse", "step_types": ["subgraph_query"], "label": "Traverse Graph"},
    {"phase": "assess", "step_types": ["pattern_assessment"], "label": "Assess Patterns"},
    {"phase": "retrieve", "step_types": ["book_query"], "label": "Retrieve Passages"},
    {"phase": "coverage", "step_types": ["coverage_check"], "label": "Check Coverage"},
    {"phase": "score", "step_types": ["score"], "label": "Score Architecture"},
    {"phase": "failure_scenarios", "step_types": ["failure_scenarios"], "label": "Generate Failure Scenarios"},
    {"phase": "critique", "step_types": ["critique"], "label": "Critique Consultation"},
    {"phase": "synthesize", "step_types": ["synthesis"], "label": "Synthesize Report"},
    {"phase": "generate_plan", "step_types": ["implementation_plan_generated"], "label": "Generate Implementation Plan"},
    {"phase": "implement", "step_types": ["plan_step_updated"], "label": "Implement Plan Steps"},
]


def _compute_progress(record: dict) -> dict:
    """Compute workflow progress from consultation steps.

    Returns:
        Dict with completed (list), remaining (list), current_phase (str),
        progress_percent (int), step_counts (dict).
    """
    steps = record.get("steps", [])
    step_types = {s.get("type") for s in steps}

    completed = []
    remaining = []
    current_phase = None

    for phase_info in WORKFLOW_PHASES:
        phase_step_types = set(phase_info["step_types"])
        if phase_step_types & step_types:
            completed.append(phase_info["phase"])
        else:
            remaining.append(phase_info["phase"])
            if current_phase is None:
                current_phase = phase_info["phase"]

    # Count steps by type
    step_counts = {}
    for s in steps:
        t = s.get("type", "unknown")
        step_counts[t] = step_counts.get(t, 0) + 1

    total = len(WORKFLOW_PHASES)
    done = len(completed)
    pct = int((done / total) * 100) if total > 0 else 0

    return {
        "completed": completed,
        "remaining": remaining,
        "current_phase": current_phase if current_phase else "done",
        "progress_percent": pct,
        "step_counts": step_counts,
    }


def _determine_next_action(record: dict, progress: dict) -> dict:
    """Determine the next action based on current progress.

    Returns:
        Dict with action (str), tool (str), params (dict), reason (str).
    """
    current = progress["current_phase"]
    concept_ids = record.get("matched_concept_ids", [])
    cid = record["id"]

    if current == "done":
        return {
            "action": "complete",
            "tool": None,
            "params": {},
            "reason": "All workflow phases completed.",
        }

    if current == "match":
        return {
            "action": "match",
            "tool": "match_concepts",
            "params": {},
            "reason": "No concepts matched yet. Call match_concepts with a project description.",
        }

    if current == "plan":
        return {
            "action": "plan",
            "tool": "plan_consultation",
            "params": {"consultation_id": cid},
            "reason": "Concepts matched. Generate an adaptive plan.",
        }

    if current == "traverse":
        top_ids = concept_ids[:5]
        return {
            "action": "traverse",
            "tool": "get_subgraph",
            "params": {
                "concept_ids": top_ids,
                "max_hops": 2,
                "consultation_id": cid,
            },
            "reason": f"Plan ready. Traverse top {len(top_ids)} concepts.",
        }

    if current == "assess":
        return {
            "action": "assess",
            "tool": "log_pattern_assessment",
            "params": {"consultation_id": cid},
            "reason": "Graph traversed. Log pattern assessments for identified patterns.",
        }

    if current == "retrieve":
        return {
            "action": "retrieve",
            "tool": "ask_book",
            "params": {"consultation_id": cid},
            "reason": "Patterns assessed. Retrieve book passages for key concepts.",
        }

    if current == "coverage":
        return {
            "action": "coverage",
            "tool": "consultation_report",
            "params": {"consultation_id": cid},
            "reason": "Passages retrieved. Check coverage metrics before scoring.",
        }

    if current == "score":
        return {
            "action": "score",
            "tool": "score_architecture",
            "params": {"consultation_id": cid},
            "reason": "Coverage checked. Compute maturity scorecard.",
        }

    if current == "failure_scenarios":
        return {
            "action": "failure_scenarios",
            "tool": "generate_failure_scenarios",
            "params": {"consultation_id": cid},
            "reason": "Scored. Generate failure scenario walkthroughs for gaps.",
        }

    if current == "critique":
        return {
            "action": "critique",
            "tool": "critique_consultation",
            "params": {"consultation_id": cid},
            "reason": "Failure scenarios generated. Run quality critique to find remaining gaps.",
        }

    if current == "synthesize":
        return {
            "action": "synthesize",
            "tool": "generate-web-diagram",
            "params": {},
            "reason": "All analysis complete. Render the consultation as HTML.",
        }

    if current == "generate_plan":
        return {
            "action": "generate_plan",
            "tool": "generate_implementation_plan",
            "params": {"consultation_id": cid},
            "reason": "Report rendered. Ask the user if they want an implementation plan.",
        }

    if current == "implement":
        return {
            "action": "implement",
            "tool": "update_plan_step",
            "params": {"consultation_id": cid},
            "reason": "Implementation plan generated. Update step statuses as work progresses.",
        }

    return {
        "action": "unknown",
        "tool": None,
        "params": {},
        "reason": f"Unknown phase: {current}",
    }


async def supervise_consultation(consultation_id: str) -> dict:
    """Supervise consultation progress and suggest the next action.

    Returns progress metrics, next action, step summary, recent events,
    and shared state entries.

    Args:
        consultation_id: The consultation session ID.
    """
    if not consultation_id or not consultation_id.strip():
        return {"error": "consultation_id is required"}

    record = get_consultation(consultation_id)
    if record is None:
        return {"error": f"Consultation '{consultation_id}' not found"}

    progress = _compute_progress(record)
    next_action = _determine_next_action(record, progress)

    # Get recent events (last 10)
    events = get_consultation_events(consultation_id)
    event_alerts = events[-10:] if events else []

    # Get shared state
    state_entries = read_shared_state(consultation_id)

    return {
        "consultation_id": consultation_id,
        "progress": progress,
        "next_action": next_action,
        "step_summary": {
            "total_steps": len(record.get("steps", [])),
            "step_counts": progress["step_counts"],
        },
        "event_alerts": event_alerts,
        "shared_state_entries": state_entries,
    }
