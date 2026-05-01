"""RAG search against book sections, returning passages with provenance."""

from iconsult_mcp.db import (
    get_concept_relationships,
    get_consultation,
    get_project,
    list_canonical_concepts,
    log_consultation_step,
    search_sections_by_embedding,
)
from iconsult_mcp.embed import embed_query

MAX_CHARS_PER_PASSAGE = 4000
MAX_CHARS_TOTAL = 15000

QUESTION_TEMPLATES = {
    "requires": "What are the prerequisites for {from_name} and how does {to_name} fulfill them?",
    "conflicts_with": "What conflicts exist between {from_name} and {to_name}?",
    "alternative_to": "How do {from_name} and {to_name} compare as alternatives?",
    "extends": "How does {from_name} extend {to_name}?",
    "complements": "How do {from_name} and {to_name} complement each other?",
    "enables": "How does {from_name} enable {to_name}?",
    "uses": "How does {from_name} use {to_name}?",
}


def _generate_suggested_questions(concept_ids: list[str], max_questions: int = 5) -> list[str]:
    """Generate deterministic suggested questions from graph edges.

    Operates over raw `relationships`, so the question text uses source-book
    concept names. When called from a project-scoped consultation, the caller
    is expected to pass already-expanded member concept IDs.
    """
    seen = set()
    questions = []
    for cid in concept_ids:
        rels = get_concept_relationships(cid, confidence_threshold=0.5)
        for rel in rels:
            template = QUESTION_TEMPLATES.get(rel["relationship_type"])
            if not template:
                continue
            q = template.format(from_name=rel["from_name"], to_name=rel["to_name"])
            if q not in seen:
                seen.add(q)
                questions.append(q)
                if len(questions) >= max_questions:
                    return questions
    return questions


def _expand_canonical_to_members(
    canonical_ids: list[str],
    project_id: str,
) -> list[str]:
    """Expand a list of canonical concept IDs to their source-book member IDs.

    Canonical IDs not belonging to `project_id` are silently dropped (matches
    the get_subgraph 4b behaviour). Result is de-duplicated, order preserved
    by first appearance of each member.
    """
    canonicals = list_canonical_concepts(project_id)
    by_id = {c["id"]: c["member_concept_ids"] for c in canonicals}

    seen: set[str] = set()
    expanded: list[str] = []
    for cid in canonical_ids:
        members = by_id.get(cid)
        if not members:
            continue
        for m in members:
            if m not in seen:
                seen.add(m)
                expanded.append(m)
    return expanded


async def ask_book(
    question: str,
    concept_ids: list[str] | None = None,
    max_passages: int = 3,
    consultation_id: str | None = None,
    project_id: str | None = None,
) -> dict:
    """Search book sections by semantic similarity and return passages.

    Args:
        question: Natural language question to search for.
        concept_ids: Optional list of concept IDs to scope the search. When
            project-scoped, these should be canonical concept IDs from
            `match_concepts`; they're expanded to source-book members before
            the section search.
        max_passages: Maximum number of passages to return (default 3).
        consultation_id: Optional consultation ID to log this step. If the
            consultation row carries a project_id (set by `match_concepts`)
            and the explicit `project_id` arg is omitted, the project_id is
            auto-picked up from the row.
        project_id: Optional. When provided AND the project's unified KG has
            been built (`build_project_kg`), passage search is scoped to the
            project's `triaged_book_ids` and any caller-supplied canonical
            `concept_ids` are expanded to their source-book members. When
            omitted, behaviour is identical to the legacy single-book path.
    """
    if not question or not question.strip():
        return {"error": "question must be a non-empty string"}

    effective_project_id = project_id
    if effective_project_id is None and consultation_id:
        consult = get_consultation(consultation_id)
        if consult and consult.get("project_id"):
            effective_project_id = consult["project_id"]

    expanded_member_ids: list[str] | None = None
    triaged_book_ids: list[str] | None = None

    if effective_project_id:
        project = get_project(effective_project_id)
        if project is None:
            return {"error": f"Project '{effective_project_id}' not found"}
        if project.get("unified_kg_built_at") is None:
            return {
                "error": (
                    f"Project '{effective_project_id}' has not built its unified "
                    f"knowledge graph yet. Call build_project_kg(project_id="
                    f"'{effective_project_id}') first."
                )
            }
        triaged_book_ids = project.get("triaged_book_ids") or None
        if concept_ids:
            expanded_member_ids = _expand_canonical_to_members(
                concept_ids, effective_project_id
            )

    query_embedding = await embed_query(question)

    section_concept_filter = (
        expanded_member_ids
        if effective_project_id and concept_ids
        else (concept_ids if concept_ids else None)
    )

    results = search_sections_by_embedding(
        query_embedding=query_embedding,
        max_results=max_passages,
        concept_ids=section_concept_filter,
        book_ids=triaged_book_ids,
    )

    passages = []
    total_chars = 0
    for r in results:
        content = r.get("content") or ""
        if len(content) > MAX_CHARS_PER_PASSAGE:
            content = content[:MAX_CHARS_PER_PASSAGE] + "... [truncated]"

        if total_chars + len(content) > MAX_CHARS_TOTAL:
            content = content[: MAX_CHARS_TOTAL - total_chars] + "... [truncated]"

        passage = {
            "section_id": r["section_id"],
            "title": r["title"],
            "chapter": r["chapter_number"],
            "pages": (
                f"{r['approx_page_start']}-{r['approx_page_end']}"
                if r.get("approx_page_start")
                else None
            ),
            "score": r["score"],
            "content": content,
        }
        if r.get("book_id"):
            passage["book_id"] = r["book_id"]
        passages.append(passage)

        total_chars += len(content)
        if total_chars >= MAX_CHARS_TOTAL:
            break

    suggested_questions: list[str] = []
    if effective_project_id and expanded_member_ids:
        suggested_questions = _generate_suggested_questions(expanded_member_ids)
    elif concept_ids:
        suggested_questions = _generate_suggested_questions(concept_ids)

    if consultation_id:
        chapters_seen = list({p["chapter"] for p in passages if p.get("chapter")})
        books_seen = list({p["book_id"] for p in passages if p.get("book_id")})
        step_data = {
            "question": question,
            "scoped_concept_ids": concept_ids,
            "sections_returned": [p["section_id"] for p in passages],
            "chapters_seen": chapters_seen,
        }
        if effective_project_id:
            step_data["project_id"] = effective_project_id
            step_data["scope"] = "project_canonical"
            step_data["books_seen"] = books_seen
            if expanded_member_ids is not None:
                step_data["expanded_member_concept_ids"] = expanded_member_ids
        log_consultation_step(consultation_id, "ask_book", step_data)

    response = {
        "question": question,
        "scoped_to_concepts": concept_ids,
        "passage_count": len(passages),
        "passages": passages,
    }
    if suggested_questions:
        response["suggested_questions"] = suggested_questions
    if effective_project_id:
        response["project_id"] = effective_project_id
        response["scope"] = "project_canonical"
        if expanded_member_ids is not None:
            response["expanded_member_concept_ids"] = expanded_member_ids

    return response
