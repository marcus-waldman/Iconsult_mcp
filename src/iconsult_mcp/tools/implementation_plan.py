"""Generate, retrieve, and update implementation plans from consultation results.

Deterministic — no LLM calls. Reuses scoring internals to build phased,
classified implementation steps from stored pattern assessments.
"""

import json as _json
import os
from datetime import datetime, timezone

from iconsult_mcp.db import (
    get_consultation,
    get_concept_relationships,
    log_consultation_step,
    upsert_implementation_plan,
    get_implementation_plan_record,
)
from iconsult_mcp.tools.rubric_data import RUBRIC, normalize_pattern_id, get_pattern_level
from iconsult_mcp.tools.score_architecture import (
    _get_pattern_assessments,
    _compute_category_ratings,
    _compute_gap_analysis,
    _compute_roadmap,
)
from iconsult_mcp.tools.failure_scenarios import PATTERN_FAILURE_TEMPLATES

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MECHANICAL_PATTERN_IDS = frozenset({
    "simple_retry",
    "watchdog_timeout",
    "auto_healing_agent_resuscitation",
    "fallback_model_invocation",
    "rate_limited_invocation",
    "incremental_checkpointing",
    "basic_audit_logging",
})

# Patterns at "advanced" level are design decisions by default
DESIGN_DECISION_LEVEL = "advanced"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _classify_step_type(
    pattern_id: str,
    assessment: dict | None,
    alternative_edges: list[dict],
) -> str:
    """Classify a step as 'mechanical' or 'design_decision'.

    Heuristic chain:
    1. Known mechanical pattern IDs → mechanical
    2. Has code_refs in failure_context → mechanical (concrete fix)
    3. Has alternative_to edges → design_decision (choice required)
    4. L4+ pattern → design_decision
    5. Default → design_decision
    """
    if pattern_id in MECHANICAL_PATTERN_IDS:
        return "mechanical"

    if assessment:
        failure_context = assessment.get("failure_context", {})
        if failure_context and failure_context.get("code_refs"):
            return "mechanical"

    if alternative_edges:
        return "design_decision"

    # Check if advanced level → design decision
    level = get_pattern_level(pattern_id)
    if level == DESIGN_DECISION_LEVEL:
        return "design_decision"

    return "design_decision"


def _get_book_ref(pattern_id: str) -> dict:
    """Look up chapter from RUBRIC and page from PATTERN_FAILURE_TEMPLATES."""
    pid = normalize_pattern_id(pattern_id)
    chapter = None
    for cat in RUBRIC.values():
        for level_patterns in cat["levels"].values():
            for p in level_patterns:
                if p["id"] == pid:
                    chapter = cat["chapter"]
                    break
            if chapter is not None:
                break
        if chapter is not None:
            break

    page = None
    template = PATTERN_FAILURE_TEMPLATES.get(pid)
    if template and "book_ref" in template:
        page = template["book_ref"].get("page")

    ref = {}
    if chapter is not None:
        ref["chapter"] = chapter
    if page is not None:
        ref["page"] = page
    return ref


def _get_alternative_edges(pattern_id: str) -> list[dict]:
    """Get alternative_to relationship edges for a pattern."""
    try:
        rels = get_concept_relationships(pattern_id, confidence_threshold=0.3)
    except Exception:
        return []
    return [
        {
            "pattern_id": (
                r["to_concept_id"]
                if r["from_concept_id"] == pattern_id
                else r["from_concept_id"]
            ),
            "pattern_name": (
                r["to_name"]
                if r["from_concept_id"] == pattern_id
                else r["from_name"]
            ),
        }
        for r in rels
        if r["relationship_type"] == "alternative_to"
    ]


def _get_requires_edges(pattern_id: str) -> list[str]:
    """Get pattern IDs that this pattern requires (dependencies)."""
    try:
        rels = get_concept_relationships(pattern_id, confidence_threshold=0.3)
    except Exception:
        return []
    deps = []
    for r in rels:
        if r["relationship_type"] == "requires" and r["from_concept_id"] == pattern_id:
            deps.append(r["to_concept_id"])
    return deps


def _sort_steps_within_phase(
    steps: list[dict],
    requires_edges: dict[str, list[str]],
) -> list[dict]:
    """Sort steps: dependencies first, mechanical before design_decision, then by pattern name."""
    phase_pattern_ids = {s["pattern_id"] for s in steps}

    def sort_key(step):
        pid = step["pattern_id"]
        deps = requires_edges.get(pid, [])
        # Count how many dependencies are in this same phase (those should come first)
        dep_count = sum(1 for d in deps if d in phase_pattern_ids)
        # Mechanical before design_decision
        type_order = 0 if step["step_type"] == "mechanical" else 1
        return (dep_count, type_order, step["pattern_name"])

    return sorted(steps, key=sort_key)


def _compute_summary(phases: list[dict]) -> dict:
    """Compute summary statistics from phases."""
    total = 0
    mechanical = 0
    design_decisions = 0
    completed = 0
    in_progress = 0
    skipped = 0
    pending = 0

    for phase in phases:
        for step in phase["steps"]:
            total += 1
            if step["step_type"] == "mechanical":
                mechanical += 1
            else:
                design_decisions += 1

            status = step["status"]
            if status == "completed":
                completed += 1
            elif status == "in_progress":
                in_progress += 1
            elif status == "skipped":
                skipped += 1
            else:
                pending += 1

    return {
        "total_steps": total,
        "mechanical": mechanical,
        "design_decisions": design_decisions,
        "completed": completed,
        "in_progress": in_progress,
        "skipped": skipped,
        "pending": pending,
    }


def _build_plan_json(
    consultation_id: str,
    assessments: dict[str, dict],
    roadmap: list[dict],
) -> dict:
    """Assemble the full plan JSON structure from roadmap phases."""
    phases = []

    for roadmap_phase in roadmap:
        phase_steps = []
        requires_edges: dict[str, list[str]] = {}

        for pattern_info in roadmap_phase["patterns"]:
            pattern_id = normalize_pattern_id(pattern_info.get("pattern_id", ""))
            if not pattern_id:
                # Fall back to name lookup
                pattern_name = pattern_info["name"]
                for cat in RUBRIC.values():
                    for lp in cat["levels"].values():
                        for p in lp:
                            if p["name"] == pattern_name:
                                pattern_id = p["id"]
                                break
                        if pattern_id:
                            break
                    if pattern_id:
                        break

            if not pattern_id:
                continue

            assessment = assessments.get(pattern_id)
            alternative_edges = _get_alternative_edges(pattern_id)
            deps = _get_requires_edges(pattern_id)
            requires_edges[pattern_id] = deps

            step_type = _classify_step_type(pattern_id, assessment, alternative_edges)
            book_ref = _get_book_ref(pattern_id)

            # Extract file refs from failure_context
            file_refs = []
            if assessment:
                fc = assessment.get("failure_context", {})
                if fc:
                    for cr in fc.get("code_refs", []):
                        ref = cr.get("file", "")
                        if cr.get("line"):
                            ref += f":{cr['line']}"
                        if ref:
                            file_refs.append(ref)

            step = {
                "step_id": "",  # assigned after sorting
                "pattern_id": pattern_id,
                "pattern_name": pattern_info["name"],
                "step_type": step_type,
                "status": "pending",
                "current_status": pattern_info["status"],
                "evidence": assessment.get("evidence", "") if assessment else "",
                "file_refs": file_refs,
                "book_ref": book_ref,
                "dependencies": [d for d in deps if d != pattern_id],
                "alternatives": alternative_edges,
                "notes": "",
            }
            phase_steps.append(step)

        # Sort within phase
        phase_steps = _sort_steps_within_phase(phase_steps, requires_edges)

        # Assign step IDs
        phase_num = roadmap_phase["phase"]
        for i, step in enumerate(phase_steps, 1):
            step["step_id"] = f"{phase_num}.{i}"

        phases.append({
            "phase": phase_num,
            "category": roadmap_phase.get("category", ""),
            "category_name": roadmap_phase.get("category_name", ""),
            "title": f"Phase {phase_num}: {roadmap_phase.get('category_name', '')}",
            "steps": phase_steps,
            "checkpoint": f"Review Phase {phase_num} before continuing",
        })

    summary = _compute_summary(phases)

    return {
        "consultation_id": consultation_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phases": phases,
        "summary": summary,
    }


def _render_markdown(plan_json: dict, project_description: str) -> str:
    """Generate markdown with checkboxes from plan JSON."""
    lines = []
    lines.append("# Implementation Plan")
    lines.append("")
    lines.append(f"**Project:** {project_description}")
    lines.append(f"**Generated:** {plan_json['generated_at']}")
    lines.append("")

    summary = plan_json["summary"]
    lines.append(f"**Progress:** {summary['completed']}/{summary['total_steps']} steps complete")
    lines.append(f"({summary['mechanical']} mechanical, {summary['design_decisions']} design decisions)")
    lines.append("")

    for phase in plan_json["phases"]:
        lines.append(f"## {phase['title']}")
        lines.append("")

        for step in phase["steps"]:
            # Checkbox
            if step["status"] == "completed":
                checkbox = "[x]"
            elif step["status"] == "skipped":
                checkbox = "[-]"
            elif step["status"] == "in_progress":
                checkbox = "[~]"
            else:
                checkbox = "[ ]"

            type_badge = "⚙️" if step["step_type"] == "mechanical" else "🏗️"
            lines.append(f"- {checkbox} **{step['step_id']}** {type_badge} {step['pattern_name']}")
            lines.append(f"  - Status: {step['current_status']} → {step['status']}")

            if step["evidence"]:
                lines.append(f"  - Evidence: {step['evidence']}")

            if step["file_refs"]:
                refs = ", ".join(f"`{r}`" for r in step["file_refs"])
                lines.append(f"  - Files: {refs}")

            if step["book_ref"]:
                ref_parts = []
                if "chapter" in step["book_ref"]:
                    ref_parts.append(f"Ch. {step['book_ref']['chapter']}")
                if "page" in step["book_ref"]:
                    ref_parts.append(f"p. {step['book_ref']['page']}")
                if ref_parts:
                    lines.append(f"  - Book: {', '.join(ref_parts)}")

            if step["dependencies"]:
                lines.append(f"  - Dependencies: {', '.join(step['dependencies'])}")

            if step["alternatives"]:
                alt_names = [a["pattern_name"] for a in step["alternatives"]]
                lines.append(f"  - Alternatives: {', '.join(alt_names)}")

            if step["notes"]:
                lines.append(f"  - Notes: {step['notes']}")

            lines.append("")

        lines.append(f"> **Checkpoint:** {phase['checkpoint']}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 1: Generate
# ---------------------------------------------------------------------------

async def generate_implementation_plan(
    consultation_id: str,
    output_dir: str | None = None,
) -> dict:
    """Generate a phased implementation plan from consultation results.

    Builds on score_architecture internals: computes maturity level, gaps,
    and roadmap, then classifies each step as mechanical or design_decision.
    Writes a markdown checklist and stores the plan in DuckDB.

    Args:
        consultation_id: The consultation session to generate a plan for.
        output_dir: Directory for markdown file (default: ~/.agent/diagrams/).
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
            "with log_pattern_assessment before generating an implementation plan.",
            "consultation_id": consultation_id,
        }

    # Compute category ratings and roadmap
    category_ratings = _compute_category_ratings(assessments)
    gaps = _compute_gap_analysis(assessments, category_ratings)
    roadmap = _compute_roadmap(gaps, category_ratings)

    if not roadmap:
        return {
            "consultation_id": consultation_id,
            "message": "No gaps found — all patterns are implemented or not applicable.",
        }

    # Build plan
    plan_json = _build_plan_json(consultation_id, assessments, roadmap)

    # Render markdown
    project_description = record.get("project_description", "")
    markdown = _render_markdown(plan_json, project_description)

    # Write markdown file
    if output_dir is None:
        output_dir = os.path.join(os.path.expanduser("~"), ".agent", "diagrams")
    os.makedirs(output_dir, exist_ok=True)

    filename = f"implementation-plan-{consultation_id[:8]}.md"
    markdown_path = os.path.join(output_dir, filename)
    with open(markdown_path, "w", encoding="utf-8") as f:
        f.write(markdown)

    # Store in DB
    upsert_implementation_plan(consultation_id, plan_json, markdown_path)

    # Log step
    log_consultation_step(consultation_id, "implementation_plan_generated", {
        "markdown_path": markdown_path,
        "total_steps": plan_json["summary"]["total_steps"],
        "phases": len(plan_json["phases"]),
    })

    return {
        "consultation_id": consultation_id,
        "markdown_path": markdown_path,
        "summary": plan_json["summary"],
        "phases": len(plan_json["phases"]),
    }


# ---------------------------------------------------------------------------
# Tool 2: Get
# ---------------------------------------------------------------------------

async def get_implementation_plan(consultation_id: str) -> dict:
    """Retrieve a previously generated implementation plan.

    Args:
        consultation_id: The consultation session to retrieve the plan for.
    """
    if not consultation_id or not consultation_id.strip():
        return {"error": "consultation_id is required"}

    record = get_implementation_plan_record(consultation_id)
    if not record:
        return {
            "error": f"No implementation plan found for consultation '{consultation_id}'. "
            "Call generate_implementation_plan first.",
        }

    plan_json = record["plan_json"]
    return {
        "consultation_id": consultation_id,
        "plan_json": plan_json,
        "markdown_path": record["markdown_path"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "summary": plan_json.get("summary", {}),
    }


# ---------------------------------------------------------------------------
# Tool 3: Update step
# ---------------------------------------------------------------------------

VALID_STATUSES = {"pending", "in_progress", "completed", "skipped"}


async def update_plan_step(
    consultation_id: str,
    step_id: str,
    status: str,
    notes: str = "",
) -> dict:
    """Update the status of a step in an implementation plan.

    Args:
        consultation_id: The consultation session.
        step_id: The step to update (e.g. "1.1").
        status: New status: pending, in_progress, completed, or skipped.
        notes: Optional notes about the update.
    """
    if not consultation_id or not consultation_id.strip():
        return {"error": "consultation_id is required"}

    if status not in VALID_STATUSES:
        return {"error": f"Invalid status '{status}'. Must be one of: {', '.join(sorted(VALID_STATUSES))}"}

    record = get_implementation_plan_record(consultation_id)
    if not record:
        return {
            "error": f"No implementation plan found for consultation '{consultation_id}'. "
            "Call generate_implementation_plan first.",
        }

    plan_json = record["plan_json"]

    # Find the step
    found = False
    available_ids = []
    for phase in plan_json.get("phases", []):
        for step in phase.get("steps", []):
            available_ids.append(step["step_id"])
            if step["step_id"] == step_id:
                step["status"] = status
                if notes:
                    step["notes"] = notes
                found = True

    if not found:
        return {
            "error": f"Step '{step_id}' not found.",
            "available_step_ids": available_ids,
        }

    # Recompute summary
    plan_json["summary"] = _compute_summary(plan_json["phases"])

    # Update DB
    upsert_implementation_plan(consultation_id, plan_json, record["markdown_path"])

    # Regenerate markdown if path exists
    markdown_path = record["markdown_path"]
    if markdown_path:
        # Need project description for markdown
        consultation_record = get_consultation(consultation_id)
        project_description = consultation_record.get("project_description", "") if consultation_record else ""
        markdown = _render_markdown(plan_json, project_description)
        try:
            with open(markdown_path, "w", encoding="utf-8") as f:
                f.write(markdown)
        except OSError:
            pass  # Non-fatal if file can't be written

    # Log step
    log_consultation_step(consultation_id, "plan_step_updated", {
        "step_id": step_id,
        "status": status,
        "notes": notes,
    })

    return {
        "consultation_id": consultation_id,
        "step_id": step_id,
        "status": status,
        "summary": plan_json["summary"],
    }
