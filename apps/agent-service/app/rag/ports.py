"""Replaceable RAG ports.

Adapters should implement these small contracts; application code does not
need to know whether storage is in memory, a vector database, or a service.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from .models import DocumentChunk, ParsedDocument, RagStatistics, SearchHit


class DocumentParser(Protocol):
    def parse(
        self,
        payload: bytes,
        *,
        source_name: str,
        content_type: str | None = None,
        document_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> ParsedDocument: ...


class Chunker(Protocol):
    def split(self, text: str, *, metadata: dict[str, Any] | None = None) -> Sequence[str]: ...


class EmbeddingProvider(Protocol):
    dimensions: int

    def embed(self, text: str) -> Sequence[float]: ...


class VectorStore(Protocol):
    async def upsert(self, chunks: Sequence[DocumentChunk], *, namespace: str) -> None: ...

    async def search(
        self,
        query: str,
        *,
        namespace: str,
        top_k: int = 5,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[SearchHit]: ...

    async def delete_document(self, document_id: str, *, namespace: str) -> int: ...

    async def count(self, *, namespace: str | None = None) -> int: ...

    async def statistics(self, *, owner_id: str) -> RagStatistics: ...
