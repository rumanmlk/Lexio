import asyncio
import hashlib
import re
from typing import Protocol

import httpx
import numpy as np

from app.config import Settings


class Embedder(Protocol):
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    async def embed_query(self, text: str) -> list[float]: ...


class GeminiEmbedder:
    """gemini-embedding-2 over REST. It takes no task_type field; the task goes in the text."""

    BASE = "https://generativelanguage.googleapis.com/v1beta"
    BATCH = 50

    def __init__(self, api_key: str, model: str, dim: int):
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")
        self.model, self.dim = model, dim
        self.client = httpx.AsyncClient(
            base_url=self.BASE,
            headers={"x-goog-api-key": api_key},
            timeout=60,
        )

    def _item(self, text: str) -> dict:
        return {
            "model": f"models/{self.model}",
            "content": {"parts": [{"text": text}]},
            "output_dimensionality": self.dim,
        }

    async def _batch(self, texts: list[str]) -> list[list[float]]:
        body = {"requests": [self._item(t) for t in texts]}
        for attempt in range(5):
            resp = await self.client.post(f"/models/{self.model}:batchEmbedContents", json=body)
            if resp.status_code == 429 and attempt < 4:
                await asyncio.sleep(2**attempt)
                continue
            resp.raise_for_status()
            return [e["values"] for e in resp.json()["embeddings"]]
        raise RuntimeError("unreachable")

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.BATCH):
            chunk = texts[i : i + self.BATCH]
            out += await self._batch([f"title: none | text: {t}" for t in chunk])
        return out

    async def embed_query(self, text: str) -> list[float]:
        return (await self._batch([f"task: search result | query: {text}"]))[0]


class LocalEmbedder:
    """fastembed (ONNX, CPU). For local dev and eval without an API key; not shipped to Vercel."""

    QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

    def __init__(self, model: str):
        from fastembed import TextEmbedding

        self.model = TextEmbedding(model_name=model)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vecs = await asyncio.to_thread(lambda: list(self.model.embed(texts)))
        return [v.tolist() for v in vecs]

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed_documents([self.QUERY_PREFIX + text]))[0]


class HashEmbedder:
    """Deterministic feature-hashed bag of words. Zero dependencies, used by tests."""

    def __init__(self, dim: int):
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        v = np.zeros(self.dim, dtype=np.float32)
        for tok in re.findall(r"[a-z0-9]+", text.lower()):
            h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "big")
            v[h % self.dim] += 1.0 if (h >> 63) & 1 else -1.0
        n = float(np.linalg.norm(v))
        return (v / n if n else v).tolist()

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


def build_embedder(s: Settings) -> Embedder:
    if s.embedding_provider == "gemini":
        return GeminiEmbedder(s.gemini_api_key, s.gemini_embedding_model, s.embedding_dim)
    if s.embedding_provider == "local":
        return LocalEmbedder(s.local_embedding_model)
    return HashEmbedder(s.embedding_dim)
