"""Application service for document ingest and retrieval."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import os
from typing import Any
from uuid import uuid4

from .chunker import CharacterChunker
from .docling_parser import DoclingParser
from .limits import (
    DEFAULT_MAX_METADATA_BYTES,
    DEFAULT_MAX_METADATA_DEPTH,
    DEFAULT_MAX_METADATA_ITEMS,
    MetadataLimits,
)
from .memory_store import InMemoryVectorStore
from .models import (
    DocumentChunk,
    IngestRequest,
    IngestResult,
    SearchRequest,
    SearchResult,
)
from .ports import Chunker, DocumentParser, VectorStore


class RagService:
    """Coordinates parser, chunker and vector-store ports."""

    def __init__(
        self,
        *,
        parser: DocumentParser,
        chunker: Chunker,
        store: VectorStore,
        observer: Any | None = None,
        max_document_bytes: int = 8 * 1024 * 1024,
        max_metadata_bytes: int = DEFAULT_MAX_METADATA_BYTES,
        max_metadata_items: int = DEFAULT_MAX_METADATA_ITEMS,
        max_metadata_depth: int = DEFAULT_MAX_METADATA_DEPTH,
    ) -> None:
        if max_document_bytes <= 0:
            raise ValueError("max_document_bytes must be positive")
        self.parser = parser
        self.chunker = chunker
        self.store = store
        self.observer = observer
        self.max_document_bytes = max_document_bytes
        self.metadata_limits = MetadataLimits(
            max_bytes=max_metadata_bytes,
            max_items=max_metadata_items,
            max_depth=max_metadata_depth,
        )

    async def ingest(self, request: IngestRequest, *, owner_id: str = "system") -> IngestResult:
        document_id = request.document_id or uuid4().hex
        namespace = _namespace(owner_id, request.collection)
        request.validate_metadata(self.metadata_limits)
        payload = request.payload(max_bytes=self.max_document_bytes)
        if len(payload) > self.max_document_bytes:
            raise ValueError(f"document exceeds {self.max_document_bytes} bytes")
        try:
            parsed = await asyncio.to_thread(
                self.parser.parse,
                payload,
                source_name=request.source_name,
                content_type=request.content_type,
                document_id=document_id,
                metadata={**request.metadata, "owner_id": owner_id, "collection": request.collection},
            )
            texts = await asyncio.to_thread(self.chunker.split, parsed.content, metadata=parsed.metadata)
        except Exception as exc:
            await self._observe(
                "rag.ingest",
                {"source_name": request.source_name, "collection": request.collection},
                error=exc,
            )
            raise
        chunks = [
            DocumentChunk(
                chunk_id=f"{document_id}:{index}",
                document_id=document_id,
                text=text,
                ordinal=index,
                metadata={
                    **parsed.metadata,
                    "owner_id": owner_id,
                    "collection": request.collection,
                    "chunk_index": index,
                },
            )
            for index, text in enumerate(texts)
        ]
        if not chunks:
            raise ValueError("document produced no searchable chunks")
        await self.store.delete_document(document_id, namespace=namespace)
        await self.store.upsert(chunks, namespace=namespace)
        await self._observe(
            "rag.ingest",
            {
                "document_id": document_id,
                "collection": request.collection,
                "chunk_count": len(chunks),
                "parser": parsed.metadata.get("parser", "unknown"),
            },
        )
        return IngestResult(
            document_id=document_id,
            source_name=request.source_name,
            collection=request.collection,
            parser=str(parsed.metadata.get("parser", "unknown")),
            chunk_count=len(chunks),
        )

    async def search(self, request: SearchRequest, *, owner_id: str = "system") -> SearchResult:
        namespace = _namespace(owner_id, request.collection)
        request.validate_metadata(self.metadata_limits)
        try:
            hits = await self.store.search(
                request.query,
                namespace=namespace,
                top_k=request.top_k,
                metadata_filter=request.metadata_filter,
            )
        except Exception as exc:
            await self._observe(
                "rag.retrieval",
                {"collection": request.collection, "top_k": request.top_k},
                error=exc,
            )
            raise
        await self._observe(
            "rag.retrieval",
            {"collection": request.collection, "top_k": request.top_k, "hit_count": len(hits)},
        )
        return SearchResult(query=request.query, collection=request.collection, hits=hits)

    async def delete(self, document_id: str, *, owner_id: str = "system", collection: str = "default") -> int:
        return await self.store.delete_document(document_id, namespace=_namespace(owner_id, collection))

    async def count(self, *, owner_id: str | None = None, collection: str = "default") -> int:
        namespace = _namespace(owner_id, collection) if owner_id is not None else None
        return await self.store.count(namespace=namespace)

    async def _observe(self, name: str, attributes: dict[str, Any], error: Exception | None = None) -> None:
        if self.observer is None:
            return
        try:
            method = getattr(self.observer, "record_event", None)
            if method is None:
                return
            result = method(name, attributes=attributes, error=error, event_type=name)
            if inspect.isawaitable(result):
                await result
        except Exception:
            # Telemetry must never make ingest/retrieval unavailable.
            return


def _namespace(owner_id: str, collection: str) -> str:
    owner = hashlib.sha256(owner_id.encode("utf-8")).hexdigest()[:24]
    bucket = hashlib.sha256(collection.encode("utf-8")).hexdigest()[:24]
    return f"{owner}:{bucket}"


def build_default_rag_service(
    *,
    observer: Any | None = None,
    max_document_bytes: int | None = None,
    max_metadata_bytes: int | None = None,
    max_metadata_items: int | None = None,
    max_metadata_depth: int | None = None,
) -> RagService:
    max_chars = _positive_int(os.getenv("RAG_CHUNK_MAX_CHARS"), 1200)
    overlap = _nonnegative_int(os.getenv("RAG_CHUNK_OVERLAP_CHARS"), 120)
    if overlap >= max_chars:
        overlap = max(0, max_chars // 10)
    max_chunks = _positive_int(os.getenv("RAG_MAX_CHUNKS"), 10_000)
    document_limit = max_document_bytes or _positive_int(
        os.getenv("RAG_MAX_DOCUMENT_BYTES"),
        8 * 1024 * 1024,
    )
    metadata_bytes_limit = max_metadata_bytes or _positive_int(
        os.getenv("RAG_MAX_METADATA_BYTES"),
        DEFAULT_MAX_METADATA_BYTES,
    )
    metadata_items_limit = max_metadata_items or _positive_int(
        os.getenv("RAG_MAX_METADATA_ITEMS"),
        DEFAULT_MAX_METADATA_ITEMS,
    )
    metadata_depth_limit = max_metadata_depth or _positive_int(
        os.getenv("RAG_MAX_METADATA_DEPTH"),
        DEFAULT_MAX_METADATA_DEPTH,
    )
    strict_binary = _truthy(os.getenv("RAG_STRICT_BINARY", "true"))
    return RagService(
        parser=DoclingParser(strict_binary=strict_binary),
        chunker=CharacterChunker(max_chars=max_chars, overlap_chars=overlap),
        store=InMemoryVectorStore(max_chunks=max_chunks),
        observer=observer,
        max_document_bytes=document_limit,
        max_metadata_bytes=metadata_bytes_limit,
        max_metadata_items=metadata_items_limit,
        max_metadata_depth=metadata_depth_limit,
    )


def _positive_int(raw: str | None, default: int) -> int:
    try:
        value = int(raw) if raw is not None else default
    except ValueError:
        return default
    return value if value > 0 else default


def _nonnegative_int(raw: str | None, default: int) -> int:
    try:
        value = int(raw) if raw is not None else default
    except ValueError:
        return default
    return value if value >= 0 else default


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}
