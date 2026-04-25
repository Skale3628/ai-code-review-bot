"""
Embedding Client — model-agnostic embeddings for RAG.

Supported backends (set RAG_EMBEDDING_PROVIDER in .env):
  - openai        : text-embedding-3-small / text-embedding-3-large
  - voyageai      : voyage-code-2 (best for code)
  - sentence_transformers : local, no API key needed
"""

import logging
from typing import Optional
from app.core.config import settings

logger = logging.getLogger(__name__)

_embedding_client = None


class EmbeddingClient:
    def __init__(self):
        self.provider = settings.RAG_EMBEDDING_PROVIDER
        self.model = settings.RAG_EMBEDDING_MODEL
        self.dimension = self._get_dimension()

    def _get_dimension(self) -> int:
        dims = {
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
            "voyage-code-2": 1536,
            "all-MiniLM-L6-v2": 384,
        }
        return dims.get(self.model, 1536)

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns list of float vectors."""
        if not texts:
            return []

        if self.provider == "openai":
            return await self._embed_openai(texts)
        elif self.provider == "voyageai":
            return await self._embed_voyage(texts)
        elif self.provider == "sentence_transformers":
            return self._embed_local(texts)
        else:
            raise ValueError(f"Unknown embedding provider: {self.provider}")

    async def embed_query(self, query: str) -> list[float]:
        results = await self.embed_texts([query])
        return results[0]

    async def _embed_openai(self, texts: list[str]) -> list[list[float]]:
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise RuntimeError("pip install openai")

        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        # OpenAI has a 2048 token limit per text; truncate conservatively
        truncated = [t[:6000] for t in texts]
        response = await client.embeddings.create(
            model=self.model,
            input=truncated,
        )
        return [item.embedding for item in response.data]

    async def _embed_voyage(self, texts: list[str]) -> list[list[float]]:
        try:
            import voyageai
        except ImportError:
            raise RuntimeError("pip install voyageai")

        client = voyageai.AsyncClient(api_key=settings.VOYAGE_API_KEY)
        result = await client.embed(texts, model=self.model, input_type="document")
        return result.embeddings

    def _embed_local(self, texts: list[str]) -> list[list[float]]:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise RuntimeError("pip install sentence-transformers")

        model = SentenceTransformer(self.model)
        embeddings = model.encode(texts, show_progress_bar=False)
        return embeddings.tolist()


def get_embedding_client() -> EmbeddingClient:
    global _embedding_client
    if _embedding_client is None:
        _embedding_client = EmbeddingClient()
    return _embedding_client
