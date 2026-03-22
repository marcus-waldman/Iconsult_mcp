"""Deterministic architecture scoring from stored pattern assessments.

Category-based rubric sourced from Chapter 12.  Reads pattern_assessment
steps logged during graph traversal and computes per-category ratings
using fixed formulas.  Same consultation always produces same scores.
"""

from iconsult_mcp.db import get_consultation, get_concept_relationships
from iconsult_mcp.tools.rubric_data import (
    RUBRIC,
    ALL_PATTERN_IDS,
    _PATTERN_ID_ALIASES,
    _PATTERN_ID_ALIAS_COMBINED,
    normalize_pattern_id,
    get_pattern_category,
    get_pattern_level,
)

# ---------------------------------------------------------------------------
# Re-export aliases so downstream code (failure_scenarios, render_report)
# that imports from score_architecture keeps working.
# ---------------------------------------------------------------------------

# Legacy MATURITY_MODEL — kept as thin wrapper for backward compat in tests/
# downstream consumers that haven't migrated yet.
MATURITY_MODEL = RUBRIC  # alias; callers should migrate to RUBRIC

# Per-pattern recommended metrics from Ch. 7 (Table 7.2), Ch. 8 (Table 8.2),
# Ch. 9 (Table 9.3). Keys may use old or new pattern IDs — lookups go through
# normalize_pattern_id().
PATTERN_METRICS: dict[str, dict] = {
    # Ch. 9 — Agent-level
    "single_agent_baseline": {
        "metric": "Task completion rate / tool call success rate",
        "instrumentation": "Log final outcome of each task (success/failure). Monitor failed tool API calls.",
        "source": "Ch. 9, Table 9.3",
    },
    "agent_specific_memory": {
        "metric": "Session coherence score / reduction in repeated questions",
        "instrumentation": "Human raters score conversation quality. Track repeated information requests.",
        "source": "Ch. 9, Table 9.3",
    },
    "fractal_cot_embedding": {
        "metric": "Self-correction trigger rate / reduction in final errors",
        "instrumentation": "Track how often critique step identifies a flaw. Compare preliminary vs final error rate.",
        "source": "Ch. 9, Table 9.3",
    },
    # Ch. 7 — Robustness
    "simple_retry": {
        "metric": "Recovery rate (%)",
        "instrumentation": "Count successful retries versus initial failures.",
        "source": "Ch. 7, Table 7.2",
    },
    "watchdog_timeout": {
        "metric": "P99 latency & violation rate",
        "instrumentation": "99th percentile response time; timeout violations per hour.",
        "source": "Ch. 7, Table 7.2",
    },
    "auto_healing_agent_resuscitation": {
        "metric": "Resuscitation success rate (%)",
        "instrumentation": "Logs of successful agent restarts after a crash.",
        "source": "Ch. 7, Table 7.2",
    },
    "trust_decay_and_scoring": {
        "metric": "Agent reliability trend",
        "instrumentation": "Rolling performance window (success/failure rate) for each agent.",
        "source": "Ch. 7, Table 7.2",
    },
    "fallback_model_invocation": {
        "metric": "Accuracy delta (%)",
        "instrumentation": "Compare fallback vs primary model output accuracy on golden dataset.",
        "source": "Ch. 7, Table 7.2",
    },
    "majority_voting": {
        "metric": "Conflict rate (%)",
        "instrumentation": "Percentage of tasks requiring escalation due to lack of majority consensus.",
        "source": "Ch. 7, Table 7.2",
    },
    "canary_agent_testing": {
        "metric": "Regression rate (%)",
        "instrumentation": "Percentage of canary outputs showing negative drift from stable version.",
        "source": "Ch. 7, Table 7.2",
    },
    # Ch. 8 — Human-Agent Interaction
    "agent_calls_human": {
        "metric": "Escalation rate / resolution time",
        "instrumentation": "Log every escalation event. Measure time from escalation to human response.",
        "source": "Ch. 8, Table 8.2",
    },
    "human_calls_agent": {
        "metric": "First-contact resolution rate / average response time",
        "instrumentation": "Percentage of queries solved in single turn. End-to-end latency.",
        "source": "Ch. 8, Table 8.2",
    },
    "agent_delegates_to_agent": {
        "metric": "Orchestration overhead / sub-task failure rate",
        "instrumentation": "Log timestamps for each inter-agent delegation. Track specialist agent errors.",
        "source": "Ch. 8, Table 8.2",
    },
    "agent_calls_proxy_agent": {
        "metric": "External API error rate / security incidents",
        "instrumentation": "Monitor proxy agent logs for failed/timed-out API calls.",
        "source": "Ch. 8, Table 8.2",
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_pattern_assessments(record: dict) -> dict[str, dict]:
    """Extract pattern assessments from consultation steps, keyed by canonical pattern_id.

    Normalises each pattern_id via aliases so that lookups by either old
    MATURITY_MODEL IDs, KG concept IDs, or new rubric IDs all succeed.
    """
    assessments: dict[str, dict] = {}
    for step in record.get("steps", []):
        if step.get("type") == "pattern_assessment":
            raw_pid = step.get("pattern_id")
            if not raw_pid:
                continue
            canonical = normalize_pattern_id(raw_pid)
            # Store under canonical ID (and raw ID as fallback)
            if canonical not in assessments:
                assessments[canonical] = step
            if raw_pid != canonical and raw_pid not in assessments:
                assessments[raw_pid] = step
    return assessments


def _is_pattern_met(assessment: dict | None) -> bool:
    """Determine if a pattern is met from its assessment.

    When indicators are present: all applicable (non-N/A) indicators must be met.
    When indicators are absent (backward compat): status must be 'implemented'
    or 'not_applicable'.
    """
    if assessment is None:
        return False

    status = assessment.get("status", "missing")
    if status == "not_applicable":
        return True

    # Indicator-based assessment (new style)
    indicators = assessment.get("indicators")
    if indicators:
        applicable = [i for i in indicators if not i.get("na", False)]
        if not applicable:
            return True  # All N/A
        return all(i.get("met", False) for i in applicable)

    # Status-based assessment (backward compat)
    return status == "implemented"


def _compute_category_ratings(assessments: dict[str, dict]) -> dict[str, dict]:
    """Compute per-category ratings from pattern assessments.

    Returns dict keyed by category key with:
      - name, rating, levels (each with met flag + pattern details)
    """
    levels_in_order = ("basic", "intermediate", "advanced")
    results: dict[str, dict] = {}

    for cat_key, cat in RUBRIC.items():
        non_empty_levels = [
            lv for lv in levels_in_order if cat["levels"].get(lv)
        ]

        # Check if any pattern in this category has been assessed
        has_any_assessment = False
        any_indicator_met = False

        level_results: dict[str, dict] = {}
        highest_met_level = None

        for lv in levels_in_order:
            patterns = cat["levels"].get(lv, [])
            if not patterns:
                level_results[lv] = {"met": True, "patterns": [], "empty": True}
                continue

            pattern_details = []
            all_met = True
            for p in patterns:
                a = assessments.get(p["id"])
                met = _is_pattern_met(a)
                status = a["status"] if a else "not_assessed"

                if a:
                    has_any_assessment = True
                if met and status != "not_applicable":
                    any_indicator_met = True
                if not met:
                    all_met = False

                # Indicator detail
                indicator_summary = None
                if a and a.get("indicators"):
                    inds = a["indicators"]
                    applicable = [i for i in inds if not i.get("na", False)]
                    indicator_summary = {
                        "total": len(inds),
                        "met": sum(1 for i in applicable if i.get("met", False)),
                        "not_met": sum(1 for i in applicable if not i.get("met", False)),
                        "na": sum(1 for i in inds if i.get("na", False)),
                    }

                pattern_details.append({
                    "pattern_id": p["id"],
                    "pattern_name": p["name"],
                    "status": status,
                    "met": met,
                    "evidence": a.get("evidence", "") if a else "",
                    "indicator_summary": indicator_summary,
                })

            level_results[lv] = {
                "met": all_met,
                "patterns": pattern_details,
                "empty": False,
            }

        # Determine highest met level (sequential — must be consecutive)
        for lv in non_empty_levels:
            if level_results[lv]["met"]:
                highest_met_level = lv
            else:
                break

        # Compute rating
        if not has_any_assessment:
            rating = "not_started"
        elif highest_met_level == non_empty_levels[-1]:
            rating = "mature"
        elif highest_met_level is not None:
            rating = "established"
        elif any_indicator_met:
            rating = "emerging"
        else:
            rating = "not_started"

        results[cat_key] = {
            "name": cat["name"],
            "chapter": cat["chapter"],
            "rating": rating,
            "levels": level_results,
        }

    return results


def _compute_gap_analysis(
    assessments: dict[str, dict],
    category_ratings: dict[str, dict],
) -> list[dict]:
    """Identify gaps — patterns not yet met, with severity."""
    gaps = []

    for cat_key, cat in RUBRIC.items():
        cat_rating = category_ratings[cat_key]

        for lv in ("basic", "intermediate", "advanced"):
            patterns = cat["levels"].get(lv, [])
            for p in patterns:
                a = assessments.get(p["id"])
                if _is_pattern_met(a):
                    continue

                # Severity: check for requires/conflicts_with edges
                severity = "WARNING"
                try:
                    rels = get_concept_relationships(p["id"], confidence_threshold=0.3)
                    has_prereq = any(r["relationship_type"] == "requires" for r in rels)
                    has_conflict = any(r["relationship_type"] == "conflicts_with" for r in rels)
                    if has_prereq or has_conflict:
                        severity = "CRITICAL"
                except Exception:
                    pass

                # Compliance/security patterns are always CRITICAL
                if p["id"] in (
                    "instruction_fidelity_auditing",
                    "agent_auth_and_authz",
                ):
                    severity = "CRITICAL"

                # Missing indicators detail
                missing_indicators = []
                if a and a.get("indicators"):
                    for ind in a["indicators"]:
                        if not ind.get("met", False) and not ind.get("na", False):
                            missing_indicators.append(ind.get("text", ""))

                gaps.append({
                    "pattern_id": p["id"],
                    "pattern_name": p["name"],
                    "category": cat_key,
                    "category_name": cat["name"],
                    "level": lv,
                    "status": a["status"] if a else "not_assessed",
                    "severity": severity,
                    "chapter": cat["chapter"],
                    "missing_indicators": missing_indicators,
                })

    return gaps


def _compute_recommended_metrics(
    gaps: list[dict],
    assessments: dict[str, dict],
) -> list[dict]:
    """Return book-defined metrics for gap/partial patterns."""
    metrics = []
    seen: set[str] = set()

    for gap in gaps:
        pid = gap["pattern_id"]
        if pid in PATTERN_METRICS and pid not in seen:
            seen.add(pid)
            m = PATTERN_METRICS[pid]
            metrics.append({
                "pattern_id": pid,
                "pattern_name": gap["pattern_name"],
                "category": gap["category"],
                "metric": m["metric"],
                "instrumentation": m["instrumentation"],
                "source": m["source"],
            })
    return metrics


def _compute_roadmap(
    gaps: list[dict],
    category_ratings: dict[str, dict],
) -> list[dict]:
    """Group gaps into phases — weakest categories first, then by level."""
    # Rating priority: not_started > emerging > established
    rating_priority = {"not_started": 0, "emerging": 1, "established": 2, "mature": 3}

    # Group gaps by category
    cat_gaps: dict[str, list[dict]] = {}
    for g in gaps:
        cat_gaps.setdefault(g["category"], []).append(g)

    # Sort categories by rating (weakest first)
    sorted_cats = sorted(
        cat_gaps.keys(),
        key=lambda c: rating_priority.get(category_ratings[c]["rating"], 9),
    )

    phases = []
    for cat_key in sorted_cats:
        cat_gap_list = cat_gaps[cat_key]
        # Group by level within category
        level_order = {"basic": 0, "intermediate": 1, "advanced": 2}
        cat_gap_list.sort(key=lambda g: level_order.get(g["level"], 9))

        phases.append({
            "phase": len(phases) + 1,
            "category": cat_key,
            "category_name": category_ratings[cat_key]["name"],
            "current_rating": category_ratings[cat_key]["rating"],
            "patterns": [
                {
                    "pattern_id": g["pattern_id"],
                    "name": g["pattern_name"],
                    "level": g["level"],
                    "status": g["status"],
                    "severity": g["severity"],
                    "missing_indicators": g.get("missing_indicators", []),
                }
                for g in cat_gap_list
            ],
        })
    return phases


def _compute_coverage_warnings(category_ratings: dict[str, dict]) -> list[str]:
    """Warn about categories with zero assessments."""
    warnings = []
    for cat_key, cat in category_ratings.items():
        has_patterns = any(
            not lv.get("empty", False)
            for lv in cat["levels"].values()
        )
        if has_patterns and cat["rating"] == "not_started":
            # Check if truly not started (no assessments) vs all missing
            all_not_assessed = all(
                p["status"] == "not_assessed"
                for lv in cat["levels"].values()
                for p in lv.get("patterns", [])
            )
            if all_not_assessed:
                warnings.append(
                    f"{cat['name']}: no patterns assessed — "
                    f"category score may be inaccurate"
                )
    return warnings


# ---------------------------------------------------------------------------
# Main tool
# ---------------------------------------------------------------------------

async def score_architecture(
    consultation_id: str,
    target_level: int | None = None,
    roadmap_levels: int = 3,
) -> dict:
    """Compute deterministic architecture maturity scores from stored assessments.

    Args:
        consultation_id: The consultation session to score.
        target_level: Unused (kept for backward compat). Ignored.
        roadmap_levels: Unused (kept for backward compat). Ignored.
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
            "hint": "Use log_pattern_assessment with indicators from the rubric.",
        }

    # Compute category ratings
    category_ratings = _compute_category_ratings(assessments)

    # Compute gap analysis + metrics + roadmap
    gaps = _compute_gap_analysis(assessments, category_ratings)
    recommended_metrics = _compute_recommended_metrics(gaps, assessments)
    roadmap = _compute_roadmap(gaps, category_ratings)
    coverage_warnings = _compute_coverage_warnings(category_ratings)

    # Summary stats
    total_assessed = len({
        pid for pid, a in assessments.items()
        if pid in ALL_PATTERN_IDS
    })
    implemented = sum(
        1 for pid in ALL_PATTERN_IDS
        if _is_pattern_met(assessments.get(pid))
        and assessments.get(pid, {}).get("status") != "not_applicable"
    )
    not_applicable = sum(
        1 for pid in ALL_PATTERN_IDS
        if assessments.get(pid, {}).get("status") == "not_applicable"
    )
    not_met = sum(
        1 for pid in ALL_PATTERN_IDS
        if pid in assessments and not _is_pattern_met(assessments.get(pid))
    )

    return {
        "consultation_id": consultation_id,
        "scoring_method": "category-based rubric (Ch. 12)",
        "categories": category_ratings,
        "overall_summary": {
            "total_patterns_in_rubric": len(ALL_PATTERN_IDS),
            "total_assessed": total_assessed,
            "implemented": implemented,
            "not_met": not_met,
            "not_applicable": not_applicable,
            "categories_assessed": sum(
                1 for c in category_ratings.values() if c["rating"] != "not_started"
            ),
            "categories_not_started": sum(
                1 for c in category_ratings.values() if c["rating"] == "not_started"
            ),
        },
        "coverage_warnings": coverage_warnings,
        "gap_analysis": gaps,
        "recommended_metrics": recommended_metrics,
        "roadmap": roadmap,
    }
