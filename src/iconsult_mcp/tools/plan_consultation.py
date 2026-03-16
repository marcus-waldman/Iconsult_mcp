"""Multi-agent planning for consultation sessions.

Generates an adaptive plan based on project complexity after match_concepts.
Runs once to produce a step sequence that the orchestrator follows.
"""

from iconsult_mcp.db import get_consultation, log_consultation_step

# Complexity keywords that push score higher
_COMPLEXITY_KEYWORDS = [
    "multi-agent", "distributed", "consensus", "orchestrat",
    "microservice", "event-driven", "real-time", "fault-toleran",
    "human-in-the-loop", "guardrail", "compliance", "security",
]


def _assess_complexity(
    matched_count: int,
    description: str,
    relationship_density: float,
) -> dict:
    """Assess project complexity from matched concepts and description.

    Args:
        matched_count: Number of matched concepts.
        description: Project description text.
        relationship_density: Average relationships per matched concept (0-10+).

    Returns:
        Dict with level ('simple', 'moderate', 'complex'), score (0-100), reasons.
    """
    score = 0
    reasons = []

    # Concept count signal (0-35 points)
    if matched_count >= 12:
        score += 35
        reasons.append(f"{matched_count} concepts matched (high)")
    elif matched_count >= 7:
        score += 20
        reasons.append(f"{matched_count} concepts matched (moderate)")
    else:
        score += 10
        reasons.append(f"{matched_count} concepts matched (low)")

    # Keyword signal (0-35 points)
    desc_lower = description.lower()
    keyword_hits = [kw for kw in _COMPLEXITY_KEYWORDS if kw in desc_lower]
    kw_score = min(35, len(keyword_hits) * 7)
    score += kw_score
    if keyword_hits:
        reasons.append(f"Complexity keywords: {', '.join(keyword_hits[:5])}")

    # Relationship density signal (0-30 points)
    if relationship_density >= 4.0:
        score += 30
        reasons.append(f"High relationship density ({relationship_density:.1f})")
    elif relationship_density >= 2.0:
        score += 15
        reasons.append(f"Moderate relationship density ({relationship_density:.1f})")
    else:
        score += 5
        reasons.append(f"Low relationship density ({relationship_density:.1f})")

    if score >= 65:
        level = "complex"
    elif score >= 30:
        level = "moderate"
    else:
        level = "simple"

    return {"level": level, "score": score, "reasons": reasons}


def _generate_plan(
    complexity: dict,
    matched_count: int,
    concept_ids: list[str],
) -> list[dict]:
    """Generate an adaptive plan based on complexity assessment.

    Returns a list of step dicts, each with: step_number, action, tool,
    params (dict), and description.
    """
    level = complexity["level"]
    steps = []
    step_num = 0

    # --- Common: plan creation is step 0 (already done) ---

    if level == "simple":
        top_n = min(3, matched_count)
        max_hops = 1

        step_num += 1
        steps.append({
            "step_number": step_num,
            "action": "traverse",
            "tool": "get_subgraph",
            "params": {"concept_ids": concept_ids[:top_n], "max_hops": max_hops},
            "description": f"Traverse top {top_n} concepts at {max_hops} hop",
        })

        step_num += 1
        steps.append({
            "step_number": step_num,
            "action": "assess",
            "tool": "log_pattern_assessment",
            "params": {},
            "description": "Log pattern assessments for identified patterns",
        })

        step_num += 1
        steps.append({
            "step_number": step_num,
            "action": "retrieve",
            "tool": "ask_book",
            "params": {"max_passages": 3},
            "description": "Retrieve book passages for key concepts",
        })

        step_num += 1
        steps.append({
            "step_number": step_num,
            "action": "coverage",
            "tool": "consultation_report",
            "params": {},
            "description": "Check coverage metrics",
        })

        step_num += 1
        steps.append({
            "step_number": step_num,
            "action": "score",
            "tool": "score_architecture",
            "params": {},
            "description": "Compute maturity scorecard",
        })

        step_num += 1
        steps.append({
            "step_number": step_num,
            "action": "failure_scenarios",
            "tool": "generate_failure_scenarios",
            "params": {"max_scenarios": 3},
            "description": "Generate failure scenario walkthroughs for gaps",
        })

        step_num += 1
        steps.append({
            "step_number": step_num,
            "action": "synthesize",
            "tool": "generate-web-diagram",
            "params": {},
            "description": "Render consultation as HTML",
        })

        step_num += 1
        steps.append({
            "step_number": step_num,
            "action": "generate_plan",
            "tool": "generate_implementation_plan",
            "params": {},
            "description": "Offer implementation plan (ask user first)",
        })

    elif level == "moderate":
        top_n = min(5, matched_count)
        max_hops = 2

        step_num += 1
        steps.append({
            "step_number": step_num,
            "action": "traverse",
            "tool": "get_subgraph",
            "params": {"concept_ids": concept_ids[:top_n], "max_hops": max_hops},
            "description": f"Traverse top {top_n} concepts at {max_hops} hops",
        })

        step_num += 1
        steps.append({
            "step_number": step_num,
            "action": "assess",
            "tool": "log_pattern_assessment",
            "params": {},
            "description": "Log pattern assessments for identified patterns",
        })

        step_num += 1
        steps.append({
            "step_number": step_num,
            "action": "retrieve",
            "tool": "ask_book",
            "params": {"max_passages": 5},
            "description": "Retrieve book passages for key concepts",
        })

        step_num += 1
        steps.append({
            "step_number": step_num,
            "action": "follow_up",
            "tool": "ask_book",
            "params": {"max_passages": 3},
            "description": "Follow up on suggested questions from graph edges",
        })

        step_num += 1
        steps.append({
            "step_number": step_num,
            "action": "coverage",
            "tool": "consultation_report",
            "params": {},
            "description": "Check coverage metrics",
        })

        step_num += 1
        steps.append({
            "step_number": step_num,
            "action": "score",
            "tool": "score_architecture",
            "params": {},
            "description": "Compute maturity scorecard",
        })

        step_num += 1
        steps.append({
            "step_number": step_num,
            "action": "failure_scenarios",
            "tool": "generate_failure_scenarios",
            "params": {},
            "description": "Generate failure scenario walkthroughs for gaps",
        })

        step_num += 1
        steps.append({
            "step_number": step_num,
            "action": "critique",
            "tool": "critique_consultation",
            "params": {},
            "description": "Optional quality critique (skip if coverage is high)",
        })

        step_num += 1
        steps.append({
            "step_number": step_num,
            "action": "synthesize",
            "tool": "generate-web-diagram",
            "params": {},
            "description": "Render consultation as HTML",
        })

        step_num += 1
        steps.append({
            "step_number": step_num,
            "action": "generate_plan",
            "tool": "generate_implementation_plan",
            "params": {},
            "description": "Offer implementation plan (ask user first)",
        })

    else:  # complex
        top_n = min(8, matched_count)
        max_hops = 2

        step_num += 1
        steps.append({
            "step_number": step_num,
            "action": "traverse",
            "tool": "get_subgraph",
            "params": {
                "concept_ids": concept_ids[:top_n],
                "max_hops": max_hops,
                "use_subagents": True,
            },
            "description": f"Scatter-gather: subagents traverse top {top_n} concepts at {max_hops} hops",
        })

        step_num += 1
        steps.append({
            "step_number": step_num,
            "action": "assess",
            "tool": "log_pattern_assessment",
            "params": {},
            "description": "Log pattern assessments for all identified patterns",
        })

        step_num += 1
        steps.append({
            "step_number": step_num,
            "action": "traverse_round2",
            "tool": "get_subgraph",
            "params": {"max_hops": 1},
            "description": "Second traversal round on newly discovered concepts",
        })

        step_num += 1
        steps.append({
            "step_number": step_num,
            "action": "retrieve",
            "tool": "ask_book",
            "params": {"max_passages": 5},
            "description": "Retrieve book passages for key concepts",
        })

        step_num += 1
        steps.append({
            "step_number": step_num,
            "action": "follow_up",
            "tool": "ask_book",
            "params": {"max_passages": 3},
            "description": "Follow up on suggested questions from graph edges",
        })

        step_num += 1
        steps.append({
            "step_number": step_num,
            "action": "coverage",
            "tool": "consultation_report",
            "params": {},
            "description": "Check coverage metrics",
        })

        step_num += 1
        steps.append({
            "step_number": step_num,
            "action": "score",
            "tool": "score_architecture",
            "params": {},
            "description": "Compute maturity scorecard",
        })

        step_num += 1
        steps.append({
            "step_number": step_num,
            "action": "failure_scenarios",
            "tool": "generate_failure_scenarios",
            "params": {},
            "description": "Generate failure scenario walkthroughs for gaps",
        })

        step_num += 1
        steps.append({
            "step_number": step_num,
            "action": "critique",
            "tool": "critique_consultation",
            "params": {},
            "description": "Mandatory quality critique — address prompt_mutations",
        })

        step_num += 1
        steps.append({
            "step_number": step_num,
            "action": "synthesize",
            "tool": "generate-web-diagram",
            "params": {},
            "description": "Render consultation as HTML",
        })

        step_num += 1
        steps.append({
            "step_number": step_num,
            "action": "generate_plan",
            "tool": "generate_implementation_plan",
            "params": {},
            "description": "Offer implementation plan (ask user first)",
        })

    return steps


async def plan_consultation(consultation_id: str) -> dict:
    """Generate an adaptive consultation plan based on matched concepts.

    Should be called once after match_concepts. Reads the consultation record,
    assesses complexity, and generates a step-by-step plan.

    Args:
        consultation_id: The consultation session ID from match_concepts.
    """
    if not consultation_id or not consultation_id.strip():
        return {"error": "consultation_id is required"}

    record = get_consultation(consultation_id)
    if record is None:
        return {"error": f"Consultation '{consultation_id}' not found"}

    concept_ids = record.get("matched_concept_ids", [])
    description = record.get("project_description", "")

    if not concept_ids:
        return {"error": "No matched concepts found — run match_concepts first"}

    # Estimate relationship density from the DB
    from iconsult_mcp.db import get_concept_relationships
    total_rels = 0
    sample = concept_ids[:5]
    for cid in sample:
        rels = get_concept_relationships(cid, confidence_threshold=0.3)
        total_rels += len(rels)
    density = total_rels / len(sample) if sample else 0.0

    complexity = _assess_complexity(len(concept_ids), description, density)
    plan = _generate_plan(complexity, len(concept_ids), concept_ids)

    log_consultation_step(consultation_id, "plan_created", {
        "complexity": complexity,
        "step_count": len(plan),
    })

    return {
        "consultation_id": consultation_id,
        "complexity": complexity,
        "plan": plan,
        "step_count": len(plan),
    }
