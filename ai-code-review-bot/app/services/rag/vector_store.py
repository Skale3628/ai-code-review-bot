"""
Vector Store — FAISS-backed in-process store with hybrid retrieval.

Hybrid retrieval = semantic (FAISS cosine) + keyword (BM25-style TF-IDF).
Final score = alpha * semantic_score + (1 - alpha) * keyword_score

One store per repo_id. Stores are kept in memory and optionally persisted
to disk at RAG_INDEX_PATH for restart survival.
"""

import logging
import math
import pickle
import re
from collections import defaultdict
from pathlib import Path
from typing import Optional

from app.services.rag.chunker import CodeChunk

logger = logging.getLogger(__name__)

HYBRID_ALPHA = 0.7          # weight for semantic vs keyword
TOP_K_DEFAULT = 8


class BM25Index:
    """Minimal BM25 index over CodeChunk content."""

    K1 = 1.5
    B = 0.75

    def __init__(self):
        self.chunks: list[CodeChunk] = []
        self.tf: list[dict[str, float]] = []
        self.df: dict[str, int] = defaultdict(int)
        self.avgdl: float = 0.0

    def _tokenize(self, text: str) -> list[str]:
        return re.findall(r"[a-zA-Z_]\w*", text.lower())

    def add_chunks(self, chunks: list[CodeChunk]):
        self.chunks = chunks
        total_len = 0
        for chunk in chunks:
            tokens = self._tokenize(chunk.content)
            total_len += len(tokens)
            freq: dict[str, float] = defaultdict(float)
            for tok in tokens:
                freq[tok] += 1
            self.tf.append(dict(freq))
            for tok in set(tokens):
                self.df[tok] += 1
        self.avgdl = total_len / max(len(chunks), 1)

    def score(self, query: str, top_k: int) -> list[tuple[int, float]]:
        """Return list of (chunk_index, score) sorted descending."""
        tokens = self._tokenize(query)
        N = len(self.chunks)
        scores: list[float] = []

        for idx, tf in enumerate(self.tf):
            dl = sum(tf.values())
            score = 0.0
            for tok in tokens:
                if tok not in tf:
                    continue
                idf = math.log((N - self.df[tok] + 0.5) / (self.df[tok] + 0.5) + 1)
                tf_val = tf[tok] * (self.K1 + 1) / (
                    tf[tok] + self.K1 * (1 - self.B + self.B * dl / self.avgdl)
                )
                score += idf * tf_val
            scores.append(score)

        ranked = sorted(enumerate(scores), key=lambda x: -x[1])
        return ranked[:top_k]


class VectorStore:
    """Per-repo FAISS + BM25 hybrid vector store."""

    def __init__(self, repo_id: str, dimension: int):
        self.repo_id = repo_id
        self.dimension = dimension
        self.chunks: list[CodeChunk] = []
        self.bm25 = BM25Index()
        self._index = None          # FAISS index, lazy-loaded

    def _get_faiss(self):
        if self._index is not None:
            return self._index
        try:
            import faiss
            self._index = faiss.IndexFlatIP(self.dimension)  # Inner product = cosine on normalized vecs
            return self._index
        except ImportError:
            raise RuntimeError(
                "FAISS not installed. Run: pip install faiss-cpu\n"
                "Or disable RAG: RAG_ENABLED=false in .env"
            )

    def add_chunks(self, chunks: list[CodeChunk]):
        import numpy as np

        embeddings = [c.embedding for c in chunks if c.embedding is not None]
        if not embeddings:
            logger.warning(f"[{self.repo_id}] No embeddings to index")
            return

        matrix = np.array(embeddings, dtype="float32")
        # L2-normalize for cosine similarity via inner product
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        matrix = matrix / np.maximum(norms, 1e-9)

        index = self._get_faiss()
        index.add(matrix)
        self.chunks.extend(chunks)
        self.bm25.add_chunks(self.chunks)

        logger.info(f"[{self.repo_id}] Indexed {len(chunks)} chunks, total={len(self.chunks)}")

    def search(
        self, query_embedding: list[float], query_text: str, top_k: int = TOP_K_DEFAULT
    ) -> list[CodeChunk]:
        import numpy as np

        if not self.chunks:
            return []

        index = self._get_faiss()
        k = min(top_k * 2, len(self.chunks))

        # Semantic search
        q_vec = np.array([query_embedding], dtype="float32")
        q_vec /= np.maximum(np.linalg.norm(q_vec), 1e-9)
        distances, indices = index.search(q_vec, k)

        semantic_scores: dict[int, float] = {}
        for dist, idx in zip(distances[0], indices[0]):
            if idx >= 0:
                semantic_scores[idx] = float(dist)

        # BM25 keyword search
        keyword_hits = self.bm25.score(query_text, k)
        max_bm25 = max((s for _, s in keyword_hits), default=1.0) or 1.0
        keyword_scores: dict[int, float] = {
            idx: score / max_bm25 for idx, score in keyword_hits
        }

        # Max semantic score for normalization
        max_sem = max(semantic_scores.values(), default=1.0) or 1.0

        # Combine
        all_indices = set(semantic_scores) | set(keyword_scores)
        combined: list[tuple[int, float]] = []
        for idx in all_indices:
            sem = semantic_scores.get(idx, 0.0) / max_sem
            kw = keyword_scores.get(idx, 0.0)
            final = HYBRID_ALPHA * sem + (1 - HYBRID_ALPHA) * kw
            combined.append((idx, final))

        combined.sort(key=lambda x: -x[1])
        return [self.chunks[i] for i, _ in combined[:top_k] if i < len(self.chunks)]

    def save(self, path: Path):
        import faiss
        path.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(path / "faiss.index"))
        with open(path / "chunks.pkl", "wb") as f:
            # Don't pickle embeddings (too large), they're in FAISS
            chunks_no_emb = [
                CodeChunk(**{**c.__dict__, "embedding": None}) for c in self.chunks
            ]
            pickle.dump(chunks_no_emb, f)
        logger.info(f"[{self.repo_id}] Saved index to {path}")

    def load(self, path: Path) -> bool:
        import faiss
        idx_path = path / "faiss.index"
        chunks_path = path / "chunks.pkl"
        if not idx_path.exists() or not chunks_path.exists():
            return False
        self._index = faiss.read_index(str(idx_path))
        with open(chunks_path, "rb") as f:
            self.chunks = pickle.load(f)
        self.bm25.add_chunks(self.chunks)
        logger.info(f"[{self.repo_id}] Loaded {len(self.chunks)} chunks from {path}")
        return True


# ── Global registry of per-repo stores ──────────────────────────────────────

_stores: dict[str, VectorStore] = {}


def get_store(repo_id: str, dimension: int = 1536) -> VectorStore:
    if repo_id not in _stores:
        _stores[repo_id] = VectorStore(repo_id, dimension)
    return _stores[repo_id]
