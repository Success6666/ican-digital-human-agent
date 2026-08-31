"""Embedding adapters for local Chinese models and remote compatible APIs."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Sequence
from urllib.request import Request, urlopen


_TOKEN_RE = re.compile(r"[\w]+|[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", re.UNICODE)


class HashEmbeddingProvider:
    """Feature-hashing embedding.

    This is deliberately deterministic and local. It makes the storage port
    useful without downloading a model; production can replace it with an
    embedding service without changing :class:`InMemoryVectorStore` callers.
    """

    def __init__(self, dimensions: int = 256) -> None:
        if dimensions < 16:
            raise ValueError("dimensions must be at least 16")
        self.dimensions = dimensions

    def embed(self, text: str) -> Sequence[float]:
        vector = [0.0] * self.dimensions
        tokens = _TOKEN_RE.findall(text.casefold())
        if not tokens:
            return vector
        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            vector = [value / norm for value in vector]
        return vector


class LocalSentenceTransformerEmbeddingProvider:
    """Lazy local SentenceTransformers adapter."""

    def __init__(self, *, model: str, dimensions: int = 512) -> None:
        if not model:
            raise ValueError("local embedding model is required")
        if dimensions < 16:
            raise ValueError("dimensions must be at least 16")
        self.model_name = model
        self.dimensions = dimensions
        self._model = None

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError("本地 Embedding 需要安装 sentence-transformers 依赖") from exc
        self._model = SentenceTransformer(self.model_name)
        model_dimension = self._model.get_sentence_embedding_dimension()
        if model_dimension:
            self.dimensions = int(model_dimension)
        return self._model

    def embed(self, text: str) -> Sequence[float]:
        vector = self._load().encode(text, normalize_embeddings=True, convert_to_numpy=True)
        return [float(value) for value in vector.tolist()]


class OpenAICompatibleEmbeddingProvider:
    """Synchronous OpenAI-compatible embedding adapter executed off-loop."""

    def __init__(self, *, base_url: str, api_key: str, model: str, dimensions: int = 1536, timeout_seconds: float = 8.0) -> None:
        if not base_url or not api_key or not model:
            raise ValueError("base_url, api_key and model are required")
        if dimensions < 16:
            raise ValueError("dimensions must be at least 16")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dimensions = dimensions
        self.timeout_seconds = timeout_seconds

    def embed(self, text: str) -> Sequence[float]:
        request = Request(
            f"{self.base_url}/embeddings",
            data=json.dumps({"model": self.model, "input": text}).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310 - URL is operator config, not user input.
            payload = json.loads(response.read().decode("utf-8"))
        values = payload.get("data", [{}])[0].get("embedding") if isinstance(payload, dict) else None
        if not isinstance(values, list) or not values:
            raise RuntimeError("embedding service returned no vector")
        return [float(value) for value in values]


def build_embedding_provider(*, provider: str, base_url: str, api_key: str, model: str, dimensions: int):
    if provider.casefold() in {"local", "sentence-transformers", "sentence_transformers", "bge"}:
        return LocalSentenceTransformerEmbeddingProvider(model=model or "BAAI/bge-small-zh-v1.5", dimensions=dimensions or 512)
    if provider.casefold() in {"openai", "openai-compatible", "compatible"} and base_url and api_key and model:
        return OpenAICompatibleEmbeddingProvider(base_url=base_url, api_key=api_key, model=model, dimensions=dimensions)
    return HashEmbeddingProvider(dimensions=dimensions)
