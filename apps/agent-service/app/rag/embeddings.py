"""Dependency-free deterministic embeddings for the first in-memory backend."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence


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
