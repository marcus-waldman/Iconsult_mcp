"""RAG search against book sections, returning passages with provenance."""

from iconsult_mcp.db import search_sections_by_embedding
from iconsult_mcp.embed import embed_query

MAX_CHARS_PER_PASSAGE = 4000
MAX_CHARS_TOTAL = 15000


async def ask_book(
    question: str,
    concept_ids: list[str] | None = None,
    max_passages: int = 3,
) -> dict:
    """Search book sections by semantic similarity and return passages.

    Args:
        question: Natural language question to search for.
        concept_ids: Optional list of concept IDs to scope the search.
        max_passages: Maximum number of passages to return (default 3).
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

    return {
        "question": question,
        "scoped_to_concepts": concept_ids,
        "passage_count": len(passages),
        "passages": passages,
    }
