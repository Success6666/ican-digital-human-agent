"""Bounded in-memory vector store used by the first deployment."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .embeddings import HashEmbeddingProvider
from .models import CollectionStatistics, DocumentChunk, RagStatistics, SearchHit
from .ports import EmbeddingProvider


@dataclass(slots=True)
class _StoredChunk:
    chunk: DocumentChunk
    vector: Sequence[float]


class InMemoryVectorStore:
    """A small, bounded store with deterministic cosine retrieval.

    The async methods make it a drop-in adapter for a remote vector database.
    A lock protects updates and searches when multiple FastAPI requests arrive
    concurrently; no age-based deletion is performed.
    """

    def __init__(
        self,
        *,
        embedder: EmbeddingProvider | None = None,
        max_chunks: int = 10_000,
    ) -> None:
        if max_chunks < 1:
            raise ValueError("max_chunks must be positive")
        self.embedder = embedder or HashEmbeddingProvider()
        self.max_chunks = max_chunks
        self._items: OrderedDict[tuple[str, str], _StoredChunk] = OrderedDict()
        self._lock = asyncio.Lock()

    async def upsert(self, chunks: Sequence[DocumentChunk], *, namespace: str) -> None:
        if not namespace:
            raise ValueError("namespace is required")
        prepared: list[tuple[tuple[str, str], DocumentChunk, Sequence[float]]] = []
        for chunk in chunks:
            vector = await asyncio.to_thread(self.embedder.embed, chunk.text)
            prepared.append(((namespace, chunk.chunk_id), chunk, vector))
        async with self._lock:
            for key, chunk, vector in prepared:
                self._items[key] = _StoredChunk(chunk=chunk, vector=vector)
                self._items.move_to_end(key)
            while len(self._items) > self.max_chunks:
                self._items.popitem(last=False)

    async def search(
        self,
        query: str,
        *,
        namespace: str,
        top_k: int = 5,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[SearchHit]:
        if not query.strip():
            return []
        top_k = max(1, min(top_k, 50))
        query_vector = await asyncio.to_thread(self.embedder.embed, query)
        metadata_filter = metadata_filter or {}
        async with self._lock:
            snapshot = [
                stored
                for (item_namespace, _), stored in self._items.items()
                if item_namespace == namespace and _matches(stored.chunk.metadata, metadata_filter)
            ]
        # Sorting and cosine calculations happen outside the storage lock so a
        # large namespace does not block concurrent ingest/delete operations.
        candidates = [
            SearchHit(chunk=stored.chunk, score=round(_cosine(query_vector, stored.vector), 8))
            for stored in snapshot
        ]
        candidates.sort(key=lambda hit: (-hit.score, hit.chunk.ordinal, hit.chunk.chunk_id))
        return candidates[:top_k]

    async def delete_document(self, document_id: str, *, namespace: str) -> int:
        async with self._lock:
            keys = [
                key
                for key, stored in self._items.items()
                if key[0] == namespace and stored.chunk.document_id == document_id
            ]
            for key in keys:
                del self._items[key]
            return len(keys)

    async def replace_document(self, document_id: str, chunks: Sequence[DocumentChunk], *, namespace: str) -> None:
        await self.delete_document(document_id, namespace=namespace)
        await self.upsert(chunks, namespace=namespace)

    async def count(self, *, namespace: str | None = None) -> int:
        async with self._lock:
            if namespace is None:
                return len(self._items)
            return sum(1 for key in self._items if key[0] == namespace)

    async def statistics(self, *, owner_id: str) -> RagStatistics:
        async with self._lock:
            snapshot = [
                stored.chunk.model_copy(deep=False)
                for stored in self._items.values()
                if stored.chunk.metadata.get("owner_id") == owner_id
            ]

        document_ids: set[str] = set()
        collection_documents: dict[str, set[str]] = {}
        collection_chunks: dict[str, int] = {}
        for chunk in snapshot:
            collection = str(chunk.metadata.get("collection") or "default")
            document_ids.add(chunk.document_id)
            collection_documents.setdefault(collection, set()).add(chunk.document_id)
            collection_chunks[collection] = collection_chunks.get(collection, 0) + 1

        collections = [
            CollectionStatistics(
                name=name,
                documents=len(collection_documents[name]),
                chunks=collection_chunks[name],
            )
            for name in sorted(collection_documents, key=str.casefold)
        ]
        return RagStatistics(documents=len(document_ids), chunks=len(snapshot), collections=collections)

    async def clear(self) -> None:
        async with self._lock:
            self._items.clear()


def _matches(metadata: dict[str, Any], expected: dict[str, Any]) -> bool:
    return all(metadata.get(key) == value for key, value in expected.items())


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)
