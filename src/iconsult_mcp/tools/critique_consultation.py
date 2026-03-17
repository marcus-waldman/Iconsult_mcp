"""
Deterministic critique of a consultation session.

Analyzes logged steps to identify workflow gaps, coverage issues, and
quality problems. No LLM calls — pure structural analysis of consultation data.
"""

import logging
from typing import Any

from iconsult_mcp.db import get_consultation

logger = logging.getLogger(__name__)

# Expected workflow step types in order
WORKFLOW_STEPS = [
    "match_concepts",   # Step 2: concept matching (implicit — creates the consultation)
    "get_subgraph",     # Step 3: graph traversal
    "pattern_assessment",  # Step 3: pattern logging
    "ask_book",         # Step 4: passage retrieval
]

# Minimum thresholds for a thorough consultation
MIN_SUBGRAPH_TRAVERSALS = 3
MIN_PATTERN_ASSESSMENTS = 5
MIN_ASK_BOOK_QUESTIONS = 1
MIN_CONCEPT_COVERAGE = 0.5
MIN_REL_TYPE_COVERAGE = 0.4

ALL_RELATIONSHIP_TYPES = {
    "uses", "component_of", "extends", "specializes",
    "alternative_to", "requires", "precedes", "enables",
    "conflicts_with", "complements",
}

CRITICAL_EDGE_TYPES = {"requires", "conflicts_with"}


async def critique_consultation(
    consultation_id: str,
    max_iterations: int = 1,
) -> dict:
    """Produce a deterministic critique of a consultation session.

    Supports multi-iteration mode: when max_iterations > 1, the critique is
    run multiple times against the same consultation. Each iteration re-reads
    the consultation steps (which may have been updated by executing mutations
    between calls). Stops early if converged (no new errors, coverage improvement
    < 5%) or stuck (identical mutations generated twice).

    Args:
        consultation_id: The consultation session to critique.
        max_iterations: Number of critique iterations (1-3, default 1).

    Returns:
        Dict with issues, summary stats, and suggestions. Multi-iteration mode
        adds iteration_count and convergence_reason.
    """
    max_iterations = max(1, min(3, max_iterations))

    prev_severity_counts: dict = {}
    prev_mutations_key: str | None = None
    prev_coverage: float = 0.0
    iteration_results: list[dict] = []

    final_result: dict = {}

    for iteration in range(max_iterations):
        record = get_consultation(consultation_id)
        if not record:
            return {"error": f"Consultation '{consultation_id}' not found"}

        steps = record["steps"]
        matched_ids = set(record["matched_concept_ids"])

        issues: list[dict] = []
        stats = _compute_stats(steps, matched_ids)

        # Check workflow completeness
        _check_workflow(steps, issues)
        _check_traversals(stats, issues)
        _check_assessments(stats, issues)
        _check_passages(stats, issues)
        _check_coverage(stats, issues)
        _check_critical_edges(stats, issues)
        _check_failure_scenarios(stats, issues)

        severity_counts: dict = {}
        for issue in issues:
            sev = issue["severity"]
            severity_counts[sev] = severity_counts.get(sev, 0) + 1

        mutations = _build_prompt_mutations(issues, stats)

        result = {
            "consultation_id": consultation_id,
            "issue_count": len(issues),
            "severity_counts": severity_counts,
            "issues": issues,
            "stats": stats,
            "prompt_mutations": mutations,
        }
        iteration_results.append(result)
        final_result = result

        # Single iteration mode — return immediately
        if max_iterations == 1:
            return result

        # Convergence check: no new errors and coverage improvement < 5%
        current_errors = severity_counts.get("error", 0)
        prev_errors = prev_severity_counts.get("error", 0)
        current_coverage = stats.get("concept_coverage", 0.0)
        coverage_delta = current_coverage - prev_coverage

        if iteration > 0 and current_errors == 0 and coverage_delta < 0.05:
            final_result["convergence_reason"] = "converged"
            break

        # Stuck-loop detection: identical mutations generated twice
        mutations_key = str(sorted(
            (m["action"], str(sorted(m["params"].items())) if isinstance(m["params"], dict) else str(m["params"]))
            for m in mutations
        ))
        if mutations_key == prev_mutations_key:
            final_result["convergence_reason"] = "stuck_loop"
            break

        prev_severity_counts = severity_counts
        prev_mutations_key = mutations_key
        prev_coverage = current_coverage

    if max_iterations > 1:
        final_result["iteration_count"] = len(iteration_results)
        if "convergence_reason" not in final_result:
            final_result["convergence_reason"] = "max_iterations_reached"

    return final_result


def _compute_stats(steps: list[dict], matched_ids: set[str]) -> dict:
    """Compute summary statistics from consultation steps."""
    step_types = [s.get("type") for s in steps]

    # Subgraph traversals
    subgraph_steps = [s for s in steps if s.get("type") == "get_subgraph"]
    explored_seeds = set()
    discovered_ids = set()
    rel_types_seen = set()
    for s in subgraph_steps:
        explored_seeds.update(s.get("seed_concept_ids", []))
        discovered_ids.update(s.get("discovered_concept_ids", []))
        rel_types_seen.update(s.get("relationship_types_seen", []))

    # Pattern assessments
    assessments = [s for s in steps if s.get("type") == "pattern_assessment"]
    assessed_ids = set()
    statuses = {}
    for a in assessments:
        st = a.get("status", "unknown")
        statuses[st] = statuses.get(st, 0) + 1
        pid = a.get("pattern_id")
        if pid:
            assessed_ids.add(pid)

    # Book queries
    book_steps = [s for s in steps if s.get("type") == "ask_book"]
    chapters_seen = set()
    for s in book_steps:
        chapters_seen.update(s.get("chapters_seen", []))

    # Coverage: concepts are "engaged" if traversed OR assessed
    engaged_ids = explored_seeds | assessed_ids
    engaged_matched = matched_ids & engaged_ids
    concept_coverage = len(engaged_matched) / len(matched_ids) if matched_ids else 0.0
    rel_type_coverage = len(rel_types_seen & ALL_RELATIONSHIP_TYPES) / len(ALL_RELATIONSHIP_TYPES)

    return {
        "total_steps": len(steps),
        "step_types_present": sorted(set(step_types)),
        "subgraph_traversals": len(subgraph_steps),
        "concepts_matched": len(matched_ids),
        "concepts_explored": len(engaged_matched),
        "concept_coverage": round(concept_coverage, 3),
        "rel_types_seen": sorted(rel_types_seen),
        "rel_types_missing": sorted(ALL_RELATIONSHIP_TYPES - rel_types_seen),
        "rel_type_coverage": round(rel_type_coverage, 3),
        "pattern_assessments": len(assessments),
        "assessment_statuses": statuses,
        "book_questions": len(book_steps),
        "chapters_seen": sorted(chapters_seen),
        "discovered_concepts": len(discovered_ids),
        "critical_edges_checked": bool(rel_types_seen & CRITICAL_EDGE_TYPES),
        "unexplored_concepts": sorted(matched_ids - engaged_ids),
    }


def _check_workflow(steps: list[dict], issues: list[dict]) -> None:
    """Check that all workflow steps are present."""
    present = {s.get("type") for s in steps}
    for step_type in WORKFLOW_STEPS:
        if step_type not in present:
            issues.append({
                "severity": "error",
                "category": "workflow",
                "message": f"Missing workflow step: '{step_type}'",
                "suggestion": f"Execute the '{step_type}' step before synthesizing.",
            })


def _check_traversals(stats: dict, issues: list[dict]) -> None:
    """Check subgraph traversal depth."""
    count = stats["subgraph_traversals"]
    if count == 0:
        issues.append({
            "severity": "error",
            "category": "traversal",
            "message": "No subgraph traversals performed",
            "suggestion": "Call get_subgraph for each matched seed concept.",
        })
    elif count < MIN_SUBGRAPH_TRAVERSALS:
        issues.append({
            "severity": "warning",
            "category": "traversal",
            "message": f"Only {count} subgraph traversals (minimum: {MIN_SUBGRAPH_TRAVERSALS})",
            "suggestion": "Explore more seed concepts for broader coverage.",
        })


def _check_assessments(stats: dict, issues: list[dict]) -> None:
    """Check pattern assessment quality."""
    count = stats["pattern_assessments"]
    if count == 0:
        issues.append({
            "severity": "error",
            "category": "assessment",
            "message": "No pattern assessments logged",
            "suggestion": "Call log_pattern_assessment for each pattern identified in the codebase.",
        })
    elif count < MIN_PATTERN_ASSESSMENTS:
        issues.append({
            "severity": "warning",
            "category": "assessment",
            "message": f"Only {count} pattern assessments (minimum: {MIN_PATTERN_ASSESSMENTS})",
            "suggestion": "Assess more patterns — check for missing, partial, and not_applicable too.",
        })


def _check_passages(stats: dict, issues: list[dict]) -> None:
    """Check book passage retrieval."""
    count = stats["book_questions"]
    if count == 0:
        issues.append({
            "severity": "error",
            "category": "retrieval",
            "message": "No book passages retrieved",
            "suggestion": "Call ask_book with concept_ids from traversal for grounded citations.",
        })
    elif count < MIN_ASK_BOOK_QUESTIONS:
        issues.append({
            "severity": "warning",
            "category": "retrieval",
            "message": f"Only {count} book queries (minimum: {MIN_ASK_BOOK_QUESTIONS})",
            "suggestion": "Ask more questions — use suggested_questions from previous responses.",
        })


def _check_coverage(stats: dict, issues: list[dict]) -> None:
    """Check concept and relationship type coverage."""
    if stats["concept_coverage"] < MIN_CONCEPT_COVERAGE:
        issues.append({
            "severity": "warning",
            "category": "coverage",
            "message": (
                f"Concept coverage {stats['concept_coverage']:.1%} "
                f"is below {MIN_CONCEPT_COVERAGE:.0%}"
            ),
            "suggestion": "Traverse unexplored matched concepts before synthesizing.",
        })

    if stats["rel_type_coverage"] < MIN_REL_TYPE_COVERAGE:
        missing = stats["rel_types_missing"]
        issues.append({
            "severity": "warning",
            "category": "coverage",
            "message": (
                f"Relationship type coverage {stats['rel_type_coverage']:.1%} "
                f"is below {MIN_REL_TYPE_COVERAGE:.0%}. Missing: {', '.join(missing)}"
            ),
            "suggestion": "Explore concepts with diverse edge types for broader analysis.",
        })


def _check_critical_edges(stats: dict, issues: list[dict]) -> None:
    """Check that prerequisite and conflict edges were examined."""
    if not stats["critical_edges_checked"]:
        issues.append({
            "severity": "error",
            "category": "critical_edges",
            "message": "Neither 'requires' nor 'conflicts_with' edges were examined",
            "suggestion": (
                "Re-traverse with focus on prerequisite and conflict relationships — "
                "these are essential for safe recommendations."
            ),
        })


def _check_failure_scenarios(stats: dict, issues: list[dict]) -> None:
    """Check that failure scenarios were generated when missing patterns exist."""
    has_missing = stats.get("assessment_statuses", {}).get("missing", 0) > 0
    has_partial = stats.get("assessment_statuses", {}).get("partial", 0) > 0
    has_scenarios = "failure_scenarios" in stats.get("step_types_present", [])

    if (has_missing or has_partial) and not has_scenarios:
        issues.append({
            "severity": "warning",
            "category": "failure_scenarios",
            "message": (
                "Missing/partial patterns found but no failure scenarios generated. "
                "Call generate_failure_scenarios to demonstrate the impact of gaps."
            ),
            "suggestion": "Call generate_failure_scenarios with the consultation_id.",
        })


def _build_prompt_mutations(issues: list[dict], stats: dict) -> list[dict]:
    """Generate concrete prompt mutations from critique issues.

    Each mutation is a dict with:
        - action: the tool call to make (get_subgraph, ask_book, log_pattern_assessment)
        - params: suggested parameters for the call
        - reason: why this mutation addresses the issue

    The LLM client can use these to adaptively retry the consultation.
    Cap at 5 mutations to prevent unbounded loops.
    """
    mutations: list[dict] = []

    # Unexplored concepts → suggest get_subgraph calls
    unexplored = stats.get("unexplored_concepts", [])
    if unexplored:
        # Batch up to 3 unexplored concepts per traversal
        for i in range(0, min(len(unexplored), 6), 3):
            batch = unexplored[i:i + 3]
            mutations.append({
                "action": "get_subgraph",
                "params": {"concept_ids": batch, "max_hops": 1, "include_descriptions": True},
                "reason": f"Explore {len(batch)} unexplored matched concepts",
            })

    # Missing critical edges → suggest targeted traversal
    if not stats.get("critical_edges_checked", False):
        # Use any explored concepts to re-traverse with focus on edges
        explored = [c for c in (stats.get("unexplored_concepts", []) or [])[:3]]
        if not explored:
            explored = ["*"]  # Signal to use any available concept
        mutations.append({
            "action": "get_subgraph",
            "params": {"concept_ids": explored, "max_hops": 2},
            "reason": "Traverse deeper to discover requires/conflicts_with edges",
        })

    # Missing pattern assessments → suggest assessment calls
    if stats.get("pattern_assessments", 0) < MIN_PATTERN_ASSESSMENTS:
        mutations.append({
            "action": "log_pattern_assessment",
            "params": {},
            "reason": (
                f"Only {stats.get('pattern_assessments', 0)} assessments logged. "
                f"Assess more patterns from the codebase (target: {MIN_PATTERN_ASSESSMENTS}+)."
            ),
        })

    # No book queries → suggest ask_book
    if stats.get("book_questions", 0) == 0:
        mutations.append({
            "action": "ask_book",
            "params": {"question": "What are the key architectural patterns for this system?"},
            "reason": "No book passages retrieved — ground recommendations in book citations.",
        })

    # Missing/partial patterns but no failure scenarios → suggest generation
    has_gaps = (
        stats.get("assessment_statuses", {}).get("missing", 0) > 0
        or stats.get("assessment_statuses", {}).get("partial", 0) > 0
    )
    has_scenarios = "failure_scenarios" in stats.get("step_types_present", [])
    if has_gaps and not has_scenarios:
        mutations.append({
            "action": "generate_failure_scenarios",
            "params": {},
            "reason": "Missing/partial patterns found — generate failure scenarios to demonstrate impact.",
        })

    return mutations[:5]
