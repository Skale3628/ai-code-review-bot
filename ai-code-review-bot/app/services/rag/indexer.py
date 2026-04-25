"""
Repo Indexer — fetches source files from GitHub or GitLab,
chunks them, embeds, and stores in the vector store.

Called:
  - On first PR review for a repo (lazy init)
  - On push to default branch (keep index fresh)
  - Manually via POST /rag/index

Files fetched respect the same skip patterns as the diff reviewer.
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional

import httpx

from app.core.config import settings
from app.services.rag.chunker import CodeChunk, chunk_file
from app.services.rag.embeddings import get_embedding_client
from app.services.rag.vector_store import VectorStore, get_store
from app.utils.diff_utils import detect_language, should_skip_file

logger = logging.getLogger(__name__)

BATCH_SIZE = 32          # Chunks per embedding API call
MAX_FILE_SIZE_BYTES = 100_000


def _repo_cache_path(repo_id: str) -> Path:
    base = Path(settings.RAG_INDEX_PATH)
    safe = repo_id.replace("/", "__")
    return base / safe


async def _fetch_github_tree(repo: str, ref: str = "HEAD") -> list[dict]:
    """Fetch flat file tree from GitHub API."""
    url = f"https://api.github.com/repos/{repo}/git/trees/{ref}?recursive=1"
    headers = {"Authorization": f"Bearer {settings.GITHUB_TOKEN}",
               "Accept": "application/vnd.github+json"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
    tree = resp.json().get("tree", [])
    return [item for item in tree if item.get("type") == "blob"]


async def _fetch_github_file(repo: str, path: str, ref: str = "HEAD") -> Optional[str]:
    url = f"https://api.github.com/repos/{repo}/contents/{path}?ref={ref}"
    headers = {"Authorization": f"Bearer {settings.GITHUB_TOKEN}",
               "Accept": "application/vnd.github.raw+json"}
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text


async def _fetch_gitlab_tree(project_id: int, ref: str = "HEAD") -> list[dict]:
    url = (
        f"{settings.GITLAB_BASE_URL}/api/v4/projects/{project_id}"
        f"/repository/tree?recursive=true&per_page=100&ref={ref}"
    )
    headers = {"PRIVATE-TOKEN": settings.GITLAB_TOKEN}
    items = []
    page = 1
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            resp = await client.get(url + f"&page={page}", headers=headers)
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            items.extend([i for i in batch if i.get("type") == "blob"])
            page += 1
    return items


async def _fetch_gitlab_file(project_id: int, path: str, ref: str = "HEAD") -> Optional[str]:
    import urllib.parse
    encoded = urllib.parse.quote(path, safe="")
    url = (
        f"{settings.GITLAB_BASE_URL}/api/v4/projects/{project_id}"
        f"/repository/files/{encoded}/raw?ref={ref}"
    )
    headers = {"PRIVATE-TOKEN": settings.GITLAB_TOKEN}
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text


async def _embed_chunks_in_batches(chunks: list[CodeChunk]) -> list[CodeChunk]:
    """Embed all chunks, respecting API batch limits."""
    embedder = get_embedding_client()
    results = []

    for i in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[i : i + BATCH_SIZE]
        texts = [c.content for c in batch]
        try:
            embeddings = await embedder.embed_texts(texts)
            for chunk, emb in zip(batch, embeddings):
                chunk.embedding = emb
            results.extend(batch)
        except Exception as e:
            logger.error(f"Embedding batch {i//BATCH_SIZE} failed: {e}")
            # Skip failed batch rather than crashing entire index

    return [c for c in results if c.embedding is not None]


async def index_github_repo(
    repo: str, ref: str = "HEAD", force: bool = False
) -> VectorStore:
    """
    Index a GitHub repo. Returns the populated VectorStore.
    Uses cached index if available and force=False.
    """
    repo_id = f"github:{repo}"
    store = get_store(repo_id)
    cache_path = _repo_cache_path(repo_id)

    if not force and store.load(cache_path):
        logger.info(f"[{repo_id}] Using cached index ({len(store.chunks)} chunks)")
        return store

    logger.info(f"[{repo_id}] Indexing repo (ref={ref})...")
    tree = await _fetch_github_tree(repo, ref)

    all_chunks: list[CodeChunk] = []
    sem = asyncio.Semaphore(5)  # Max 5 concurrent file fetches

    async def process_file(item: dict):
        path = item["path"]
        size = item.get("size", 0)
        if should_skip_file(path) or size > MAX_FILE_SIZE_BYTES:
            return
        language = detect_language(path)
        if settings.REVIEW_LANGUAGES and language not in settings.REVIEW_LANGUAGES:
            return
        async with sem:
            content = await _fetch_github_file(repo, path, ref)
        if content:
            chunks = chunk_file(path, content, repo_id, language)
            all_chunks.extend(chunks)

    await asyncio.gather(*[process_file(item) for item in tree])
    logger.info(f"[{repo_id}] Generated {len(all_chunks)} chunks from {len(tree)} files")

    embedded = await _embed_chunks_in_batches(all_chunks)
    store.add_chunks(embedded)
    store.save(cache_path)
    return store


async def index_gitlab_repo(
    project_id: int, repo_name: str, ref: str = "HEAD", force: bool = False
) -> VectorStore:
    repo_id = f"gitlab:{project_id}"
    store = get_store(repo_id)
    cache_path = _repo_cache_path(repo_id)

    if not force and store.load(cache_path):
        logger.info(f"[{repo_id}] Using cached index")
        return store

    logger.info(f"[{repo_id}] Indexing GitLab project {repo_name} (ref={ref})...")
    tree = await _fetch_gitlab_tree(project_id, ref)

    all_chunks: list[CodeChunk] = []
    sem = asyncio.Semaphore(5)

    async def process_file(item: dict):
        path = item["path"]
        if should_skip_file(path):
            return
        language = detect_language(path)
        async with sem:
            content = await _fetch_gitlab_file(project_id, path, ref)
        if content and len(content.encode()) <= MAX_FILE_SIZE_BYTES:
            chunks = chunk_file(path, content, repo_id, language)
            all_chunks.extend(chunks)

    await asyncio.gather(*[process_file(item) for item in tree])

    embedded = await _embed_chunks_in_batches(all_chunks)
    store.add_chunks(embedded)
    store.save(cache_path)
    return store
