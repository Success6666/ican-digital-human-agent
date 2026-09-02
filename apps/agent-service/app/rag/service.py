"""Application service for document ingest and retrieval."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import replace
import hashlib
import inspect
import os
import time
from typing import Any
from uuid import uuid4

from .chunker import CharacterChunker, ChunkDraft, HierarchicalChunker
from .docling_parser import DoclingParser
from .docling_parser import DoclingRuntimeConfig
from .embeddings import build_embedding_provider
from .faiss_store import FaissVectorStore
from .limits import (
    DEFAULT_MAX_METADATA_BYTES,
    DEFAULT_MAX_METADATA_DEPTH,
    DEFAULT_MAX_METADATA_ITEMS,
    MetadataLimits,
)
from .models import (
    DocumentChunk,
    IngestRequest,
    IngestResult,
    SearchRequest,
    SearchResult,
    RagStatistics,
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
        parse_concurrency: int = 1,
        search_cache_ttl_seconds: float = 30.0,
        search_cache_max_entries: int = 2048,
    ) -> None:
        if max_document_bytes <= 0:
            raise ValueError("max_document_bytes must be positive")
        if parse_concurrency <= 0:
            raise ValueError("parse_concurrency must be positive")
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
        self.parse_concurrency = parse_concurrency
        self._parse_slots = asyncio.Semaphore(parse_concurrency)
        self.search_cache_ttl_seconds = max(0.0, search_cache_ttl_seconds)
        self.search_cache_max_entries = max(1, search_cache_max_entries)
        self._search_cache: OrderedDict[tuple[Any, ...], tuple[float, SearchResult]] = OrderedDict()
        self._search_cache_lock = asyncio.Lock()

    async def warmup_embedding(self) -> None:
        """Load the configured local/remote embedder before first user query."""
        await asyncio.to_thread(self.store.embedder.embed, "数字人知识库检索预热")

    async def ingest(self, request: IngestRequest, *, owner_id: str = "system") -> IngestResult:
        started = time.perf_counter()
        document_id = request.document_id or uuid4().hex
        namespace = _namespace(owner_id, request.collection)
        request.validate_metadata(self.metadata_limits)
        payload = request.payload(max_bytes=self.max_document_bytes)
        if len(payload) > self.max_document_bytes:
            raise ValueError(f"document exceeds {self.max_document_bytes} bytes")
        try:
            async with self._parse_slots:
                parsed = await asyncio.to_thread(
                    self.parser.parse,
                    payload,
                    source_name=request.source_name,
                    # JSON ``content`` is explicitly text even when callers
                    # use a generated source name without a file extension.
                    # Keep base64 uploads extension-driven so strict binary
                    # parsing remains unchanged.
                    content_type=request.content_type
                    or ("text/plain" if request.content is not None else None),
                    document_id=document_id,
                    metadata={**request.metadata, "owner_id": owner_id, "collection": request.collection},
                )
                split_with_metadata = getattr(self.chunker, "split_with_metadata", None)
                if callable(split_with_metadata):
                    drafts = await asyncio.to_thread(split_with_metadata, parsed.content, metadata=parsed.metadata)
                else:
                    drafts = [ChunkDraft(text=text, metadata={}) for text in await asyncio.to_thread(self.chunker.split, parsed.content, metadata=parsed.metadata)]
        except Exception as exc:
            await self._observe(
                "rag.ingest",
                {
                    "source_name": request.source_name,
                    "collection": request.collection,
                    "document_bytes": len(payload),
                    "duration_ms": _elapsed_ms(started),
                },
                error=exc,
            )
            raise
        chunks = [
            DocumentChunk(
                chunk_id=f"{document_id}:{index}",
                document_id=document_id,
                text=draft.text,
                ordinal=index,
                metadata={
                    **parsed.metadata,
                    **draft.metadata,
                    "owner_id": owner_id,
                    "collection": request.collection,
                    "chunk_index": index,
                },
            )
            for index, draft in enumerate(drafts)
        ]
        if not chunks:
            raise ValueError("document produced no searchable chunks")
        replace_document = getattr(self.store, "replace_document", None)
        if callable(replace_document):
            await replace_document(document_id, chunks, namespace=namespace)
        else:
            await self.store.delete_document(document_id, namespace=namespace)
            await self.store.upsert(chunks, namespace=namespace)
        await self._invalidate_search_cache(namespace)
        await self._observe(
            "rag.ingest",
            {
                "document_id": document_id,
                "collection": request.collection,
                "chunk_count": len(chunks),
                "parser": parsed.metadata.get("parser", "unknown"),
                "document_bytes": len(payload),
                "duration_ms": _elapsed_ms(started),
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
        started = time.perf_counter()
        namespace = _namespace(owner_id, request.collection)
        request.validate_metadata(self.metadata_limits)
        cache_key = (namespace, request.query.strip(), request.top_k, _freeze(request.metadata_filter))
        if self.search_cache_ttl_seconds > 0:
            async with self._search_cache_lock:
                cached = self._search_cache.get(cache_key)
                if cached and cached[0] > time.monotonic():
                    self._search_cache.move_to_end(cache_key)
                    return cached[1].model_copy(deep=True)
                if cached:
                    self._search_cache.pop(cache_key, None)
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
                {
                    "collection": request.collection,
                    "top_k": request.top_k,
                    "query_length": len(request.query),
                    "duration_ms": _elapsed_ms(started),
                },
                error=exc,
            )
            raise
        await self._observe(
            "rag.retrieval",
            {
                "collection": request.collection,
                "top_k": request.top_k,
                "hit_count": len(hits),
                "query_length": len(request.query),
                "top_score": round(hits[0].score, 8) if hits else None,
                "duration_ms": _elapsed_ms(started),
            },
        )
        result = SearchResult(query=request.query, collection=request.collection, hits=hits)
        if self.search_cache_ttl_seconds > 0:
            async with self._search_cache_lock:
                self._search_cache[cache_key] = (time.monotonic() + self.search_cache_ttl_seconds, result.model_copy(deep=True))
                self._search_cache.move_to_end(cache_key)
                while len(self._search_cache) > self.search_cache_max_entries:
                    self._search_cache.popitem(last=False)
        return result

    async def delete(self, document_id: str, *, owner_id: str = "system", collection: str = "default") -> int:
        namespace = _namespace(owner_id, collection)
        deleted = await self.store.delete_document(document_id, namespace=namespace)
        if deleted:
            await self._invalidate_search_cache(namespace)
        return deleted

    async def _invalidate_search_cache(self, namespace: str) -> None:
        async with self._search_cache_lock:
            for key in [key for key in self._search_cache if key[0] == namespace]:
                self._search_cache.pop(key, None)

    async def count(self, *, owner_id: str | None = None, collection: str = "default") -> int:
        namespace = _namespace(owner_id, collection) if owner_id is not None else None
        return await self.store.count(namespace=namespace)

    async def statistics(self, *, owner_id: str) -> RagStatistics:
        return await self.store.statistics(owner_id=owner_id)

    async def _observe(self, name: str, attributes: dict[str, Any], error: Exception | None = None) -> None:
        if self.observer is None:
            return
        try:
            method = getattr(self.observer, "record_event_nonblocking", None)
            if method is None:
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
    parse_concurrency: int | None = None,
    docling_max_concurrency: int | None = None,
    store_path: str | None = None,
    index_path: str | None = None,
    embedding_provider: str | None = None,
    embedding_base_url: str | None = None,
    embedding_api_key: str | None = None,
    embedding_model: str | None = None,
    embedding_dimensions: int | None = None,
) -> RagService:
    max_chars = _positive_int(os.getenv("RAG_CHUNK_MAX_CHARS"), 720)
    overlap = _nonnegative_int(os.getenv("RAG_CHUNK_OVERLAP_CHARS"), 80)
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
    parse_concurrency_limit = parse_concurrency or _positive_int(
        os.getenv("RAG_PARSE_CONCURRENCY"),
        1,
    )
    strict_binary = _truthy(os.getenv("RAG_STRICT_BINARY", "true"))
    docling_config = DoclingRuntimeConfig.from_env()
    if docling_max_concurrency is not None:
        docling_config = replace(docling_config, max_concurrency=docling_max_concurrency)
    embedder = build_embedding_provider(
        provider=embedding_provider or os.getenv("EMBEDDING_PROVIDER", "local"),
        base_url=embedding_base_url or os.getenv("EMBEDDING_BASE_URL", ""),
        api_key=embedding_api_key or os.getenv("EMBEDDING_API_KEY", ""),
        model=embedding_model or os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5"),
        dimensions=embedding_dimensions or int(os.getenv("EMBEDDING_DIMENSIONS", "512")),
        device=os.getenv("EMBEDDING_DEVICE", "auto"),
        cache_dir=os.getenv("EMBEDDING_CACHE_DIR", "/app/model-cache/sentence-transformers"),
        batch_size=_positive_int(os.getenv("EMBEDDING_BATCH_SIZE"), 64),
    )
    vector_store = FaissVectorStore(
        store_path or os.getenv("RAG_STORE_PATH", "data/rag.sqlite3"),
        index_path=index_path or os.getenv("RAG_INDEX_PATH", "data/faiss"),
        embedder=embedder,
        max_chunks=max_chunks,
        index_type=os.getenv("RAG_INDEX_TYPE", "auto"),
        hnsw_min_chunks=_positive_int(os.getenv("RAG_HNSW_MIN_CHUNKS"), 256),
        hnsw_m=_positive_int(os.getenv("RAG_HNSW_M"), 32),
        hnsw_ef_search=_positive_int(os.getenv("RAG_HNSW_EF_SEARCH"), 64),
        index_cache_namespaces=_positive_int(os.getenv("RAG_INDEX_CACHE_NAMESPACES"), 64),
    )
    return RagService(
        parser=DoclingParser(strict_binary=strict_binary, config=docling_config),
        chunker=HierarchicalChunker(
            max_chars=max_chars,
            overlap_chars=overlap,
            parent_max_chars=_positive_int(os.getenv("RAG_PARENT_MAX_CHARS"), 2400),
            parent_overlap_chars=_nonnegative_int(os.getenv("RAG_PARENT_OVERLAP_CHARS"), 160),
        ),
        store=vector_store,
        observer=observer,
        max_document_bytes=document_limit,
        max_metadata_bytes=metadata_bytes_limit,
        max_metadata_items=metadata_items_limit,
        max_metadata_depth=metadata_depth_limit,
        parse_concurrency=parse_concurrency_limit,
        search_cache_ttl_seconds=_positive_float(os.getenv("RAG_SEARCH_CACHE_TTL_SECONDS"), 30.0),
        search_cache_max_entries=_positive_int(os.getenv("RAG_SEARCH_CACHE_MAX_ENTRIES"), 2048),
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


def _positive_float(raw: str | None, default: float) -> float:
    try:
        value = float(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else default


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple(sorted((str(key), _freeze(item)) for key, item in value.items()))
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted((_freeze(item) for item in value), key=repr))
    return value


def _elapsed_ms(started: float) -> float:
    return round(max(0.0, (time.perf_counter() - started) * 1000), 2)
