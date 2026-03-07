"""
Raw HTTP helpers for OpenAI embeddings and Anthropic Claude API.

Uses stdlib urllib.request instead of httpx to avoid deadlocks when
running inside the MCP server's asyncio event loop. urllib has no
event-loop awareness so it works reliably via asyncio.to_thread().
"""

import asyncio
import json
import logging
import time
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

from iconsult_mcp.config import (
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL,
    get_anthropic_api_key,
    get_openai_api_key,
)


class EmbeddingError(Exception):
    pass


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: word_count * 1.3."""
    return int(len(text.split()) * 1.3)


_MAX_TOKENS_PER_BATCH = 5_000
_MAX_ITEMS_PER_BATCH = 10
_INTER_BATCH_DELAY = 2.0
_MAX_TOKENS_PER_INPUT = 4000


def _truncate_oversized(text: str) -> str:
    """Truncate a single text if it exceeds the per-input token limit."""
    if _estimate_tokens(text) <= _MAX_TOKENS_PER_INPUT:
        return text
    max_words = int(_MAX_TOKENS_PER_INPUT / 1.3)
    words = text.split()
    return " ".join(words[:max_words])


def _split_into_batches(texts: list[str]) -> list[list[str]]:
    """Split texts into batches that fit within OpenAI's token limit."""
    batches = []
    current_batch: list[str] = []
    current_tokens = 0

    for text in texts:
        text = _truncate_oversized(text)
        text_tokens = _estimate_tokens(text)

        if current_batch and (
            current_tokens + text_tokens > _MAX_TOKENS_PER_BATCH
            or len(current_batch) >= _MAX_ITEMS_PER_BATCH
        ):
            batches.append(current_batch)
            current_batch = [text]
            current_tokens = text_tokens
        else:
            current_batch.append(text)
            current_tokens += text_tokens

    if current_batch:
        batches.append(current_batch)

    return batches


async def embed_texts(
    texts: list[str],
    dimensions: Optional[int] = None,
) -> list[list[float]]:
    """
    Generate embeddings for a list of texts via raw HTTP POST to OpenAI.

    Automatically splits large inputs into token-aware batches.
    """
    if not texts:
        return []

    api_key = get_openai_api_key()
    if not api_key:
        raise EmbeddingError("OPENAI_API_KEY environment variable not set.")

    dims = dimensions if dimensions is not None else EMBEDDING_DIMENSIONS

    batches = _split_into_batches(texts)
    all_embeddings: list[list[float]] = []

    for batch_idx, batch_texts in enumerate(batches):
        payload = json.dumps({
            "model": EMBEDDING_MODEL,
            "input": batch_texts,
            "dimensions": dims,
        }).encode()

        batch_timeout = min(300, max(15, len(batch_texts) * 5 + 10))

        def _make_request(p=payload, k=api_key, t=batch_timeout):
            req = urllib.request.Request(
                "https://api.openai.com/v1/embeddings",
                data=p,
                headers={
                    "Authorization": f"Bearer {k}",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=t) as resp:
                body = json.loads(resp.read())
            sorted_data = sorted(body["data"], key=lambda x: x["index"])
            return [item["embedding"] for item in sorted_data]

        max_retries = 7
        for attempt in range(max_retries):
            try:
                batch_result = await asyncio.to_thread(_make_request)
                all_embeddings.extend(batch_result)
                logger.info(f"Batch {batch_idx + 1}/{len(batches)}: embedded {len(batch_texts)} texts")
                break
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < max_retries - 1:
                    wait = 2 ** attempt * 10
                    logger.warning(f"Rate limited, waiting {wait}s (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(wait)
                    continue
                raise EmbeddingError(f"Failed to generate embeddings: {e}")
            except EmbeddingError:
                raise
            except Exception as e:
                raise EmbeddingError(f"Failed to generate embeddings: {e}")

        # Inter-batch delay to avoid rate limits
        if batch_idx < len(batches) - 1:
            await asyncio.sleep(_INTER_BATCH_DELAY)

    return all_embeddings


async def embed_query(query: str) -> list[float]:
    """Generate embedding for a single query string."""
    result = await embed_texts([query])
    return result[0]


async def claude_messages(
    messages: list[dict],
    model: str = "claude-sonnet-4-20250514",
    max_tokens: int = 4096,
    system: Optional[str] = None,
) -> str:
    """
    Call Anthropic Messages API via raw HTTP POST.

    Returns the text content of the first content block.
    """
    key = get_anthropic_api_key()
    if not key:
        raise ValueError("ANTHROPIC_API_KEY environment variable not set.")

    body: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system:
        body["system"] = system

    payload = json.dumps(body).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
    )

    def _do_request():
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        return data["content"][0]["text"]

    return await asyncio.to_thread(_do_request)
