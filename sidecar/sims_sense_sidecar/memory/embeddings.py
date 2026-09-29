"""Embedding providers for semantic memory search."""

from __future__ import annotations

import logging
import math
from typing import Protocol, runtime_checkable

import httpx

from ..config import Settings

logger = logging.getLogger(__name__)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors (0.0 when incomparable)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Protocol for embedding providers."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts."""
        ...

    async def embed_one(self, text: str) -> list[float]:
        """Generate embedding for a single text."""
        ...


class NoneEmbeddings:
    """Lexical fallback - no embeddings, returns empty vectors."""

    name = "none"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[] for _ in texts]

    async def embed_one(self, text: str) -> list[float]:
        return []

    async def close(self) -> None:
        return None


class CloudflareEmbeddings:
    """Cloudflare Workers AI BGE-M3 embeddings (free tier).

    Falls back to lexical (empty vectors) on any error.
    """

    name = "cloudflare"

    def __init__(self, settings: Settings):
        self.settings = settings
        config = settings.memory.embedding_provider_config or {}
        self.account_id = config.get("account_id", "")
        self.api_token = config.get("api_token", "")
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.account_id or not self.api_token:
            logger.debug("Cloudflare embeddings not configured, returning empty vectors")
            return [[] for _ in texts]

        try:
            client = self._get_client()
            url = f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/ai/run/@cf/baai/bge-m3"
            headers = {"Authorization": f"Bearer {self.api_token}", "Content-Type": "application/json"}

            # BGE-M3 expects a single text per request, batch if needed
            results = []
            for text in texts:
                resp = await client.post(url, json={"text": text}, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                if data.get("success") and data.get("result", {}).get("data"):
                    embedding = data["result"]["data"][0]
                    results.append(embedding)
                else:
                    results.append([])
            return results
        except Exception as e:
            logger.warning(f"Cloudflare embeddings failed, falling back to lexical: {e}")
            return [[] for _ in texts]

    async def embed_one(self, text: str) -> list[float]:
        result = await self.embed([text])
        return result[0] if result else []


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    """Factory function to build an embedding provider from settings."""
    provider_name = settings.memory.embedding_provider.lower()
    if provider_name == "cloudflare":
        return CloudflareEmbeddings(settings)
    return NoneEmbeddings()