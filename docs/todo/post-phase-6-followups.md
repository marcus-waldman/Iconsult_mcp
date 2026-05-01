# Post-Phase-6 follow-ups — report rendering polish

Three issues surfaced while reviewing the rendered Phase 6 6b/6c HTML reports. None block the multi-book merge gate — the comparison signal (rubric stability, cross-book canonical clusters, gulli passage diversity, provenance badges) reads clearly on the current reports. But each visibly degrades the report quality a stakeholder sees. All three are render-layer fixes that pre-existed the multi-book refactor; multi-book made them more visible.

This file is the canonical scope spec. Each section below is referenced from a corresponding GitHub issue. The work is a single side branch (`fix/report-rendering-polish`, three commits, mirrors the B1-B7 pattern) once someone picks it up post-merge.

**Source reports for reproduction:**
- `~/.agent/diagrams/phase6-baseline-7465fccc4320_20260501_053206.html` (single-book, all `arsanjani_2026`)
- `~/.agent/diagrams/phase6-multibook-7465fccc4320_20260501_054137.html` (arsanjani + gulli)
- consultation IDs are still in the DB — re-renders are cheap (`render_report` against the existing `consultation_id`).

---

## Checklist

- [ ] **B8a — Footer attribution should reflect actual triaged books, not hardcoded Arsanjani**
- [ ] **B8b — Scorecard tooltips: many patterns have no description; chapter refs lack book qualifier on multi-book consultations**
- [ ] **B8c — Implementation Recommendations need "why this matters for your system" + per-card citations**

---

## B8a — Footer attribution should reflect actual triaged books

### Symptom

The footer of every rendered report shows:

> Based on *Agentic Architectural Patterns for Building Multi-Agent Systems* (Arsanjani & Bustos, Packt 2026). Consultation date: YYYY-MM-DD.

This is hardcoded and wrong for multi-book consultations. The 6c report (`phase6-multibook-*.html`) draws assessments and passages from both `arsanjani_2026` and `gulli_2025`, but the footer credits only Arsanjani. A stakeholder reading the report would assume the gulli citations are out-of-corpus or unsourced.

### Root cause

The footer text is rendered server-side in `render_report` (or its template). It was authored when the corpus was single-book and never parameterized.

### Suggested fix

The data path is already complete:

1. From the `consultation_id`, look up `consultations.project_id`.
2. From the project, pull `projects.triaged_book_ids`.
3. For each book ID, look up `books` row metadata: `books.metadata` JSON column contains author/year/publisher/title fields (see `scripts/seed_books_table.py` for the canonical schema). Confirm the metadata shape before relying on it — if fields are missing, fall back gracefully.
4. Render the citation list dynamically: one book → "Based on *Title* (Authors, Publisher Year)"; multiple books → comma-separated list.

For consultations whose `project_id` is NULL (legacy single-book), retain the current Arsanjani-only footer as the fallback.

### Files

- `src/iconsult_mcp/tools/render_report.py` — footer rendering logic
- `src/iconsult_mcp/templates/consultation-report-template.html` — slot for the citation
- `tests/test_render_report*.py` — extend with multi-book footer regression test

### Scope risk

Low. The schema fields exist; this is templating and a single new helper that formats the citation list.

### Effort

~30 minutes including a regression test.

### Acceptance criteria

- 6b baseline re-render: footer says only Arsanjani (unchanged from current).
- 6c multibook re-render: footer says both Arsanjani and Gulli with full citations.
- Legacy `project_id=NULL` consultations: byte-identical footer to current behaviour.

---

## B8b — Scorecard tooltips: missing descriptions, ambiguous chapter refs

### Symptom

Two distinct sub-issues, both visible on the Phase 6 reports:

**B8b-1: Many scorecard rows have no tooltip at all.** The scorecard renders all 36 rubric patterns (7 categories × 3 levels × ~36 patterns). Phase 6 6b/6c assessed only 10. The remaining 26 rows render with empty `data-tt-desc` (or no `has-tooltip` class), so hovering produces nothing.

**B8b-2: Chapter refs lack book qualifier.** The tooltips that do render show `data-tt-ref="Ch. 5"` etc. With only Arsanjani in the corpus this was unambiguous (the rubric IS Arsanjani Ch. 12, foundations are Arsanjani Ch. 5-11). With Gulli also in scope, "Ch. 5" is ambiguous — readers don't know which book.

### Root cause

**B8b-1**: the template's tooltip data fields are sourced from the assessment's `evidence` text. Unassessed patterns have no assessment record, so no `data-tt-desc`. There's no fallback to a rubric-side description.

**B8b-2**: the chapter ref string in `rubric_data.py` is bare ("Ch. 5") because the rubric is locked to Arsanjani — the implicit source is fine in a single-book world.

### Suggested fix

**B8b-1** — pick one of two options before implementing:

- **(2a) Assessed-only tooltips**: leave the unassessed rows without tooltips but render a subtle "Click to assess" or muted-text hint instead of empty hover. Cleaner; less risk of surfacing stale or thin content. Recommended default.
- **(2b) Synthesize from indicators**: for unassessed patterns, build a default tooltip from the rubric's indicator list (`get_pattern_indicators(pattern_id)` in `rubric_data.py`). Result: hover shows "Indicators: <bulleted list>". More informative but more template work and risks looking like noise on a 36-row scorecard.

**B8b-2** — annotate chapter refs with their source book. The rubric chapter refs are all Arsanjani by construction, so `rubric_data.py` can be updated to store a source-prefixed string ("Arsanjani Ch. 5") without changing the rubric semantics. This is metadata clarification, not a rubric edit, so it stays inside the locked-rubric invariant.

For multi-book consultations where an assessment's `source_book_id` is `gulli_2025`, additionally render a gulli cross-reference if the canonical cluster's gulli member maps to a known gulli chapter. Pulling the gulli chapter requires either:

- **(2c)** a new field on `canonical_concepts` (e.g., `member_chapter_refs` JSON); requires schema migration — out of scope for a polish branch, but a clean future path.
- **(2d)** a runtime lookup against `sections` (each concept has section refs which include a chapter range). Cheap; no schema change. Recommended.

### Files

- `src/iconsult_mcp/tools/render_report.py` — `_enrich_tooltips` and the scorecard rendering loop
- `src/iconsult_mcp/rubric_data.py` — annotate chapter refs with "Arsanjani Ch. N" prefix (locked-rubric carve-out: metadata only, not pattern definitions)
- `src/iconsult_mcp/templates/consultation-report-template.html` — fallback hover behaviour for unassessed rows
- `tests/test_render_report*.py` — extend with tooltip-coverage and chapter-ref-format regression tests

### Scope risk

Medium. The (2a) vs (2b) decision and (2c) vs (2d) decision are real design calls. The locked-rubric carve-out for "Arsanjani Ch. 5" prefixing should be re-confirmed with the team before shipping.

### Effort

~1-2 hours depending on which sub-options are chosen. Option (2a) + (2d) is the lighter path.

### Acceptance criteria

- Every scorecard row has a meaningful hover state (tooltip OR a subtle assessed-status hint, depending on chosen option).
- Every chapter ref in tooltips includes the source book (e.g., `Arsanjani Ch. 5`).
- For multi-book consultations: assessment-driven tooltip refs that came from a gulli source carry a `Gulli Ch. N` cross-ref where derivable from the canonical cluster's member chapters.
- Single-book and legacy consultations: no regression in tooltip content.

---

## B8c — Implementation Recommendations: "why this matters for your system" + citations

### Symptom

Each Implementation Recommendation card on the rendered report shows the prescription ("wrap every Task spawn with an explicit deadline...") but lacks two things a stakeholder needs to act on it:

1. **Why this matters for *your* system specifically.** The current narrative jumps straight to the prescription. A stakeholder who hasn't read the rest of the report doesn't see the consequence of NOT implementing the pattern.
2. **References / citations.** The recommendation cites neither the rubric chapter, the source book that motivated the pattern, nor the canonical cluster the assessment landed in. A reader cannot follow up on the source material.

### Root cause

Both gaps are render-layer wiring, not missing data:

1. The "why this matters" content is **already generated** by `generate_failure_scenarios` for every missing pattern (the trigger → propagation → impact narrative). The recommendation card just doesn't splice the matching scenario in.
2. Citations are derivable from data already on the assessment + rubric:
   - Rubric chapter ref (`get_pattern_chapter` or equivalent in `rubric_data.py`)
   - `assessment.source_book_id` (which book the user assessed against)
   - `assessment.canonical_concept_id` → `canonical_concepts.member_concept_ids` → specific concept anchors per source book
   - For each member concept, `concepts.section_id` + `sections.chapter_id` give book-and-chapter precision

The recommendation card just doesn't render any of it.

### Suggested fix

Two-part templating change in `render_report`:

1. For each recommendation card, look up the matching `failure_scenarios` entry (keyed on `pattern_id`). If found, render its `impact` narrative as a "Why this matters for your system" block above the prescription. If no scenario was generated for that pattern, fall back to the rubric-side category description (or omit the block entirely — preferred over filler).
2. For each recommendation card, render a citations footer pulling:
   - **Rubric anchor**: `Arsanjani Ch. N` (after B8b-2 lands the source-prefixed refs)
   - **Source book(s)** from the assessment's provenance
   - **Specific concepts** via the canonical cluster's member IDs (linked or quoted)

If B8a + B8b-2 land first, this builds on their citation primitives.

### Files

- `src/iconsult_mcp/tools/render_report.py` — recommendation card rendering loop
- `src/iconsult_mcp/templates/consultation-report-template.html` — new "why this matters" + "citations" slots
- `tests/test_render_report*.py` — regression test for the splice behaviour

### Scope risk

Medium. Depends on B8b-2 for clean citations; could ship without it but the chapter refs would be ambiguous on multi-book reports until B8b-2 lands.

The "fall back to rubric description" path is a soft scope hazard — `rubric_data.py` may not have prose-quality category descriptions today (only indicator lists). Confirm before relying on it.

### Effort

~1-2 hours, contingent on B8a + B8b-2 ordering.

### Acceptance criteria

- Every recommendation card on the rendered report has either a "Why this matters" block (from a failure scenario) or no block at all (no filler).
- Every recommendation card has a citations footer listing the rubric chapter ref + source book(s) + specific anchored concepts.
- Single-book and multi-book consultations both render correctly; multi-book shows mixed-book citations where applicable.

---

## Recommended ordering

If a single side branch picks all three up:

1. **B8a first** — cheapest, no dependencies, immediately improves both Phase 6 reports.
2. **B8b second** — produces the source-prefixed citation primitives B8c depends on.
3. **B8c third** — builds on both predecessors.

Each as a separate commit. Branch off `feat/multi-book-kg` (or off `main` after the multi-book merge — same diff). Re-render the Phase 6 reports against the polished pipeline; the consultation_ids in the DB make this a one-liner.

## What does NOT change

- `rubric_data.py` pattern definitions, indicators, scoring math — locked.
- DB schema — no migrations needed for any of B8a/B8b/B8c (the runtime-lookup fallback in B8b-2 deliberately avoids the schema option).
- The Phase 6 comparison signal — the rendered reports already convey the merge-decision data; B8 polishes the surrounding presentation.
