"""RAG search against book sections, returning passages with provenance."""

from iconsult_mcp.db import (
    get_concept_relationships,
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
    """Generate deterministic suggested questions from graph edges."""
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


async def ask_book(
    question: str,
    concept_ids: list[str] | None = None,
    max_passages: int = 3,
    consultation_id: str | None = None,
) -> dict:
    """Search book sections by semantic similarity and return passages.

    Args:
        question: Natural language question to search for.
        concept_ids: Optional list of concept IDs to scope the search.
        max_passages: Maximum number of passages to return (default 3).
        consultation_id: Optional consultation ID to log this step.
    """
    if not question or not question.strip():
        return {"error": "question must be a non-empty string"}

    query_embedding = await embed_query(question)

    results = search_sections_by_embedding(
        query_embedding=query_embedding,
        max_results=max_passages,
        concept_ids=concept_ids if concept_ids else None,
    )

    # Format passages with truncation
    passages = []
    total_chars = 0
    for r in results:
        content = r.get("content") or ""
        if len(content) > MAX_CHARS_PER_PASSAGE:
            content = content[:MAX_CHARS_PER_PASSAGE] + "... [truncated]"

        if total_chars + len(content) > MAX_CHARS_TOTAL:
            content = content[: MAX_CHARS_TOTAL - total_chars] + "... [truncated]"

        passages.append({
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
        })

        total_chars += len(content)
        if total_chars >= MAX_CHARS_TOTAL:
            break

    # Generate suggested questions from graph edges
    suggested_questions = []
    if concept_ids:
        suggested_questions = _generate_suggested_questions(concept_ids)

    # Log step if consultation_id provided
    if consultation_id:
        chapters_seen = list({p["chapter"] for p in passages if p.get("chapter")})
        log_consultation_step(consultation_id, "ask_book", {
            "question": question,
            "scoped_concept_ids": concept_ids,
            "sections_returned": [p["section_id"] for p in passages],
            "chapters_seen": chapters_seen,
        })

    response = {
        "question": question,
        "scoped_to_concepts": concept_ids,
        "passage_count": len(passages),
        "passages": passages,
    }
    if suggested_questions:
        response["suggested_questions"] = suggested_questions

    return response
