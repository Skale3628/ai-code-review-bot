"""
RAG Retriever — given a PR diff, retrieves the most relevant
code chunks from the repo index to augment the review prompt.

Retrieval strategy:
  1. Extract symbol names and identifiers from the diff
  2. Embed the diff summary as a semantic query
  3. Run hybrid search (semantic + BM25)
  4. Deduplicate and format context for prompt injection
"""

import logging
import re
from typing import Optional

from app.services.rag.chunker import CodeChunk
from app.services.rag.embeddings import get_embedding_client
from app.services.rag.vector_store import get_store

logger = logging.getLogger(__name__)

MAX_CONTEXT_CHARS = 6000    # Total chars of RAG context to inject
TOP_K = 8


def _extract_identifiers(diff_text: str) -> list[str]:
    """Pull likely symbol names from the diff for keyword boosting."""
    added_lines = [
        line[1:] for line in diff_text.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    combined = " ".join(added_lines)
    # Match identifiers: camelCase, snake_case, PascalCase
    tokens = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]{2,}\b", combined)
    # Deduplicate, prefer longer/more specific names
    seen = set()
    unique = []
    for t in tokens:
        if t.lower() not in seen:
            seen.add(t.lower())
            unique.append(t)
    return unique[:30]


def _build_query(pr_title: str, pr_description: Optional[str], diff_snippet: str) -> str:
    """Build a natural language query for semantic embedding."""
    parts = [f"PR: {pr_title}"]
    if pr_description:
        parts.append(f"Description: {pr_description[:300]}")
    # Add first 500 chars of diff (added lines only)
    added = "\n".join(
        line[1:] for line in diff_snippet.splitlines()[:50]
        if line.startswith("+") and not line.startswith("+++")
    )
    if added:
        parts.append(f"Changed code:\n{added[:500]}")
    return "\n".join(parts)


def _format_context(chunks: list[CodeChunk]) -> str:
    """Format retrieved chunks for prompt injection."""
    parts = []
    total = 0
    for chunk in chunks:
        header = f"// {chunk.file_path}"
        if chunk.symbol_name:
            header += f" → {chunk.symbol_name}()"
        header += f" [lines {chunk.start_line}-{chunk.end_line}]"
        block = f"{header}\n{chunk.content}"
        if total + len(block) > MAX_CONTEXT_CHARS:
            break
        parts.append(block)
        total += len(block)
    return "\n\n---\n\n".join(parts)


async def retrieve_context(
    repo_id: str,
    pr_title: str,
    pr_description: Optional[str],
    diff_text: str,
) -> Optional[str]:
    """
    Main entry: retrieve relevant repo context for a PR.
    Returns formatted string ready for prompt injection, or None if RAG unavailable.
    """
    store = get_store(repo_id)
    if not store.chunks:
        logger.info(f"[{repo_id}] No index available — skipping RAG context")
        return None

    query_text = _build_query(pr_title, pr_description, diff_text)
    identifiers = _extract_identifiers(diff_text)
    # Boost query with key identifiers for BM25
    augmented_query = query_text + "\n" + " ".join(identifiers)

    try:
        embedder = get_embedding_client()
        query_embedding = await embedder.embed_query(query_text)
        chunks = store.search(query_embedding, augmented_query, top_k=TOP_K)
    except Exception as e:
        logger.error(f"RAG retrieval failed for {repo_id}: {e}")
        return None

    if not chunks:
        return None

    context = _format_context(chunks)
    logger.info(
        f"[{repo_id}] Retrieved {len(chunks)} chunks "
        f"({len(context)} chars) for PR context"
    )
    return context
