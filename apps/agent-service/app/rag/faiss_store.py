"""FAISS vector index with SQLite-backed document metadata and recovery."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import time
from collections import OrderedDict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import faiss
import numpy as np

from .embeddings import HashEmbeddingProvider
from .memory_store import _matches
from .models import CollectionStatistics, DocumentChunk, RagStatistics, SearchHit
from .ports import EmbeddingProvider
from .tuning import RetrievalTuning, retrieve
from .tuning.trace import QueryTrace


class FaissVectorStore:
    """Persistent FAISS retrieval backed by recoverable SQLite records.

    SQLite owns text, metadata and source vectors. FAISS owns nearest-neighbor
    search. A compact signature beside each index makes stale or interrupted
    index writes detectable and recoverable without losing documents.
    """

    def __init__(
        self,
        path: str,
        *,
        index_path: str | None = None,
        embedder: EmbeddingProvider | None = None,
        max_chunks: int = 10_000,
        index_type: str | None = None,
        hnsw_min_chunks: int = 256,
        hnsw_m: int = 32,
        hnsw_ef_search: int = 64,
        index_cache_namespaces: int = 64,
        tuning: RetrievalTuning | None = None,
    ) -> None:
        if not path.strip():
            raise ValueError("path is required")
        if max_chunks < 1:
            raise ValueError("max_chunks must be positive")
        self.path = Path(path)
        self.index_path = Path(index_path) if index_path else self.path.with_suffix(".faiss")
        self.embedder = embedder or HashEmbeddingProvider()
        self.max_chunks = max_chunks
        self.tuning = tuning or RetrievalTuning.from_env()
        self.index_type = (index_type or os.getenv("RAG_INDEX_TYPE", "auto")).strip().lower()
        self.hnsw_min_chunks = max(1, hnsw_min_chunks)
        self.hnsw_m = max(4, hnsw_m)
        self.hnsw_ef_search = max(8, hnsw_ef_search)
        self.index_cache_namespaces = max(1, index_cache_namespaces)
        self._write_lock = asyncio.Lock()
        self._index_cache: OrderedDict[str, tuple[tuple[int, float, int], faiss.Index]] = OrderedDict()
        self._rows_cache: OrderedDict[str, tuple[tuple[int, float, int], list[tuple[Any, ...]]]] = OrderedDict()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.index_path.mkdir(parents=True, exist_ok=True)
        self._initialize()

    async def upsert(self, chunks: Sequence[DocumentChunk], *, namespace: str) -> None:
        if not namespace:
            raise ValueError("namespace is required")
        chunk_list = list(chunks)
        vectors = await asyncio.to_thread(_embed_many, self.embedder, [chunk.text for chunk in chunk_list])
        prepared = [(namespace, chunk, vector) for chunk, vector in zip(chunk_list, vectors, strict=True)]
        async with self._write_lock:
            await asyncio.to_thread(self._upsert_sync, prepared)
            self._rows_cache.pop(namespace, None)
            await asyncio.to_thread(self._rebuild_all_sync)

    async def replace_document(self, document_id: str, chunks: Sequence[DocumentChunk], *, namespace: str) -> None:
        """Atomically replace one document and rebuild indexes once."""
        chunk_list = list(chunks)
        vectors = await asyncio.to_thread(_embed_many, self.embedder, [chunk.text for chunk in chunk_list])
        prepared = [(namespace, chunk, vector) for chunk, vector in zip(chunk_list, vectors, strict=True)]
        async with self._write_lock:
            await asyncio.to_thread(self._delete_sync, document_id, namespace)
            await asyncio.to_thread(self._upsert_sync, prepared)
            self._rows_cache.pop(namespace, None)
            await asyncio.to_thread(self._rebuild_all_sync)

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
        return await asyncio.to_thread(
            self._search_sync,
            query_vector,
            query,
            namespace,
            top_k,
            metadata_filter or {},
        )

    async def search_traced(
        self,
        query: str,
        *,
        namespace: str,
        top_k: int = 5,
        metadata_filter: dict[str, Any] | None = None,
    ) -> tuple[list[SearchHit], QueryTrace | None]:
        """Search while also returning per-stage attribution for the query.

        Offline diagnostics use this to answer *which stage* lost a passage
        instead of inferring it from parameter changes.
        """

        if not query.strip():
            return [], QueryTrace(query=query, namespace=namespace)
        top_k = max(1, min(top_k, 50))
        query_vector = await asyncio.to_thread(self.embedder.embed, query)
        return await asyncio.to_thread(
            self._search_sync_traced,
            query_vector,
            query,
            namespace,
            top_k,
            metadata_filter or {},
            trace_enabled=True,
        )

    async def delete_document(self, document_id: str, *, namespace: str) -> int:
        async with self._write_lock:
            deleted = await asyncio.to_thread(self._delete_sync, document_id, namespace)
            if deleted:
                self._rows_cache.pop(namespace, None)
                await asyncio.to_thread(self._rebuild_namespace_sync, namespace)
            return deleted

    async def count(self, *, namespace: str | None = None) -> int:
        return await asyncio.to_thread(self._count_sync, namespace)

    async def statistics(self, *, owner_id: str) -> RagStatistics:
        rows = await asyncio.to_thread(self._owner_rows, owner_id)
        document_ids: set[str] = set()
        collection_documents: dict[str, set[str]] = {}
        collection_chunks: dict[str, int] = {}
        for document_id, metadata_json in rows:
            try:
                metadata = json.loads(metadata_json)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            collection = str(metadata.get("collection") or "default")
            document_ids.add(document_id)
            collection_documents.setdefault(collection, set()).add(document_id)
            collection_chunks[collection] = collection_chunks.get(collection, 0) + 1
        collections = [
            CollectionStatistics(name=name, documents=len(collection_documents[name]), chunks=collection_chunks[name])
            for name in sorted(collection_documents, key=str.casefold)
        ]
        return RagStatistics(documents=len(document_ids), chunks=sum(collection_chunks.values()), collections=collections)

    async def clear(self) -> None:
        async with self._write_lock:
            await asyncio.to_thread(self._clear_sync)

    def invalidate(self) -> None:
        """Discard loaded indexes after an embedding configuration change."""

        self._index_cache.clear()
        self._rows_cache.clear()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS rag_chunks (
                    namespace TEXT NOT NULL,
                    chunk_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL,
                    vector_json TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (namespace, chunk_id)
                )
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_rag_chunks_namespace ON rag_chunks(namespace)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_rag_chunks_updated_at ON rag_chunks(updated_at)")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def _upsert_sync(self, prepared: Sequence[tuple[str, DocumentChunk, Sequence[float]]]) -> None:
        now = time.time()
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO rag_chunks(namespace, chunk_id, document_id, text, ordinal, metadata_json, vector_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(namespace, chunk_id) DO UPDATE SET
                    document_id=excluded.document_id, text=excluded.text, ordinal=excluded.ordinal,
                    metadata_json=excluded.metadata_json, vector_json=excluded.vector_json, updated_at=excluded.updated_at
                """,
                [
                    (
                        namespace,
                        chunk.chunk_id,
                        chunk.document_id,
                        chunk.text,
                        chunk.ordinal,
                        json.dumps(chunk.metadata, ensure_ascii=False, separators=(",", ":")),
                        json.dumps(list(vector), separators=(",", ":")),
                        now + index / 1_000_000,
                    )
                    for index, (namespace, chunk, vector) in enumerate(prepared)
                ],
            )
            excess = connection.execute("SELECT COUNT(*) - ? FROM rag_chunks", (self.max_chunks,)).fetchone()[0]
            if excess > 0:
                connection.execute(
                    "DELETE FROM rag_chunks WHERE rowid IN (SELECT rowid FROM rag_chunks ORDER BY updated_at, rowid LIMIT ?)",
                    (excess,),
                )

    def _search_sync(
        self,
        query_vector: Sequence[float],
        query_text: str,
        namespace: str,
        top_k: int,
        metadata_filter: dict[str, Any],
    ) -> list[SearchHit]:
        return self._search_sync_traced(query_vector, query_text, namespace, top_k, metadata_filter)[0]

    def _search_sync_traced(
        self,
        query_vector: Sequence[float],
        query_text: str,
        namespace: str,
        top_k: int,
        metadata_filter: dict[str, Any],
        *,
        trace_enabled: bool = False,
    ) -> tuple[list[SearchHit], QueryTrace | None]:
        """Run the hybrid retrieval pipeline and materialize the selected rows.

        Recall comes from the dense index; fusion, scoring and duplicate
        suppression come from the shared tuning pipeline, so this store and the
        in-memory store rank identically for the same inputs.
        """

        signature = self._signature(namespace)
        rows = self._read_namespace_cached(namespace, signature)
        if not rows:
            return [], QueryTrace(query=query_text, namespace=namespace) if trace_enabled else None
        query = _normalized_matrix([query_vector])
        index = self._load_index_sync(namespace, rows, expected_dimensions=query.shape[1], signature=signature)

        # A metadata filter is a non-score predicate, so it is resolved into the
        # eligibility set before ranking: unfiltered rows never consume a slot in
        # the dense probe, which is what lets the filtered path search deeper for
        # the same cost as the unfiltered one.
        allowed_positions = self._eligible_positions(rows, metadata_filter)
        if not allowed_positions:
            return [], QueryTrace(query=query_text, namespace=namespace) if trace_enabled else None

        search_count = len(rows) if metadata_filter else min(len(rows), max(top_k * self.tuning.candidate_multiplier, top_k))
        scores, positions = index.search(query, max(1, search_count))
        vector_ranked: list[int] = []
        vector_scores: list[float] = []
        for score, position in zip(scores[0].tolist(), positions[0].tolist(), strict=True):
            if position < 0:
                continue
            vector_ranked.append(int(position))
            vector_scores.append(float(score))

        outcome = retrieve(
            query=query_text,
            texts=[str(row[0]) for row in rows],
            vector_ranked=vector_ranked,
            vector_scores=vector_scores,
            top_k=top_k,
            tuning=self.tuning,
            allowed_positions=allowed_positions,
            trace_enabled=trace_enabled,
        )
        if outcome.trace is not None:
            outcome.trace.namespace = namespace

        hits: list[SearchHit] = []
        for position in outcome.positions:
            if position < 0 or position >= len(rows):
                continue
            text, document_id, chunk_id, ordinal, metadata_json, _ = rows[position]
            try:
                metadata = json.loads(metadata_json)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(metadata, dict) or not _matches(metadata, metadata_filter):
                continue
            hits.append(
                SearchHit(
                    chunk=DocumentChunk(
                        chunk_id=chunk_id,
                        document_id=document_id,
                        text=text,
                        ordinal=ordinal,
                        metadata=metadata,
                    ),
                    score=round(float(outcome.scores.get(position, 0.0)), 8),
                )
            )
        return hits, outcome.trace

    def _eligible_positions(self, rows: list[tuple[Any, ...]], metadata_filter: dict[str, Any]) -> set[int]:
        if not metadata_filter:
            return set(range(len(rows)))
        eligible: set[int] = set()
        for position, row in enumerate(rows):
            try:
                metadata = json.loads(row[4])
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(metadata, dict) and _matches(metadata, metadata_filter):
                eligible.add(position)
        return eligible

    def _load_index_sync(
        self,
        namespace: str,
        rows: list[tuple[Any, ...]],
        *,
        expected_dimensions: int,
        signature: tuple[int, float, int] | None = None,
    ) -> faiss.Index:
        signature = signature or self._signature(namespace)
        cached = self._index_cache.get(namespace)
        if cached and cached[0] == signature and cached[1].d == expected_dimensions:
            self._index_cache.move_to_end(namespace)
            return cached[1]
        index_file, signature_file = self._index_files(namespace)
        try:
            stored_signature = tuple(json.loads(signature_file.read_text(encoding="utf-8")))
            index = faiss.read_index(str(index_file))
            if stored_signature == signature and index.ntotal == len(rows) and index.d == expected_dimensions:
                self._cache_index(namespace, signature, index)
                return index
        except (FileNotFoundError, OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError):
            pass
        return self._rebuild_namespace_sync(namespace, rows=rows, expected_dimensions=expected_dimensions)

    def _rebuild_all_sync(self) -> None:
        namespaces = self._namespaces()
        live = set(namespaces)
        for namespace in namespaces:
            self._rebuild_namespace_sync(namespace)
        for namespace in list(self._index_cache):
            if namespace not in live:
                self._remove_index_files(namespace)

    def _rebuild_namespace_sync(
        self,
        namespace: str,
        *,
        rows: list[tuple[Any, ...]] | None = None,
        expected_dimensions: int | None = None,
    ) -> faiss.Index:
        rows = rows if rows is not None else self._read_namespace(namespace)
        if not rows:
            self._remove_index_files(namespace)
            dimensions = expected_dimensions or max(1, int(getattr(self.embedder, "dimensions", 1)))
            return faiss.IndexFlatIP(dimensions)
        vectors: list[Sequence[float]] = []
        for row in rows:
            try:
                vector = json.loads(row[5])
                if not isinstance(vector, list) or not vector:
                    raise ValueError("invalid vector")
                vectors.append(vector)
            except (TypeError, ValueError, json.JSONDecodeError):
                vectors.append(self.embedder.embed(str(row[0])))
        matrix = _normalized_matrix(vectors)
        if expected_dimensions is not None and matrix.shape[1] != expected_dimensions:
            matrix = _normalized_matrix([self.embedder.embed(str(row[0])) for row in rows])
            self._replace_vectors(namespace, rows, matrix)
        index = self._new_index(matrix.shape[1], len(rows))
        index.add(matrix)
        self._persist_index(namespace, index, self._signature(namespace))
        self._cache_index(namespace, self._signature(namespace), index)
        return index

    def _new_index(self, dimensions: int, count: int) -> faiss.Index:
        if self.index_type in {"hnsw", "auto"} and count >= self.hnsw_min_chunks:
            index = faiss.IndexHNSWFlat(dimensions, self.hnsw_m, faiss.METRIC_INNER_PRODUCT)
            index.hnsw.efSearch = self.hnsw_ef_search
            return index
        return faiss.IndexFlatIP(dimensions)

    def _cache_index(self, namespace: str, signature: tuple[int, float, int], index: faiss.Index) -> None:
        self._index_cache[namespace] = (signature, index)
        self._index_cache.move_to_end(namespace)
        while len(self._index_cache) > self.index_cache_namespaces:
            self._index_cache.popitem(last=False)

    def _read_namespace_cached(self, namespace: str, signature: tuple[int, float, int]) -> list[tuple[Any, ...]]:
        cached = self._rows_cache.get(namespace)
        if cached and cached[0] == signature:
            self._rows_cache.move_to_end(namespace)
            return cached[1]
        rows = self._read_namespace(namespace)
        self._rows_cache[namespace] = (signature, rows)
        self._rows_cache.move_to_end(namespace)
        while len(self._rows_cache) > self.index_cache_namespaces:
            self._rows_cache.popitem(last=False)
        return rows

    def _persist_index(self, namespace: str, index: faiss.Index, signature: tuple[int, float, int]) -> None:
        index_file, signature_file = self._index_files(namespace)
        index_file.parent.mkdir(parents=True, exist_ok=True)
        temporary_index = index_file.with_suffix(index_file.suffix + ".tmp")
        temporary_signature = signature_file.with_suffix(signature_file.suffix + ".tmp")
        faiss.write_index(index, str(temporary_index))
        temporary_signature.write_text(json.dumps(signature), encoding="utf-8")
        os.replace(temporary_index, index_file)
        os.replace(temporary_signature, signature_file)

    def _replace_vectors(
        self,
        namespace: str,
        rows: list[tuple[Any, ...]],
        matrix: np.ndarray,
    ) -> None:
        now = time.time()
        with self._connect() as connection:
            connection.executemany(
                "UPDATE rag_chunks SET vector_json = ?, updated_at = ? WHERE namespace = ? AND chunk_id = ?",
                [
                    (json.dumps(vector.tolist(), separators=(",", ":")), now + index / 1_000_000, namespace, row[2])
                    for index, (row, vector) in enumerate(zip(rows, matrix, strict=True))
                ],
            )

    def _read_namespace(self, namespace: str) -> list[tuple[Any, ...]]:
        with self._connect() as connection:
            return connection.execute(
                "SELECT text, document_id, chunk_id, ordinal, metadata_json, vector_json "
                "FROM rag_chunks WHERE namespace = ? ORDER BY rowid",
                (namespace,),
            ).fetchall()

    def _owner_rows(self, owner_id: str) -> list[tuple[str, str]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT document_id, metadata_json FROM rag_chunks").fetchall()
        return [
            (document_id, metadata_json)
            for document_id, metadata_json in rows
            if _metadata_owner(metadata_json) == owner_id
        ]

    def _delete_sync(self, document_id: str, namespace: str) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM rag_chunks WHERE namespace = ? AND document_id = ?",
                (namespace, document_id),
            )
            return cursor.rowcount

    def _count_sync(self, namespace: str | None) -> int:
        with self._connect() as connection:
            if namespace is None:
                return int(connection.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0])
            return int(connection.execute("SELECT COUNT(*) FROM rag_chunks WHERE namespace = ?", (namespace,)).fetchone()[0])

    def _clear_sync(self) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM rag_chunks")
        self._index_cache.clear()
        self._rows_cache.clear()
        for path in self.index_path.glob("*.faiss*"):
            path.unlink(missing_ok=True)

    def _namespaces(self) -> list[str]:
        with self._connect() as connection:
            return [str(row[0]) for row in connection.execute("SELECT DISTINCT namespace FROM rag_chunks")]

    def _signature(self, namespace: str) -> tuple[int, float, int]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*), COALESCE(MAX(updated_at), 0), COALESCE(SUM(rowid), 0) "
                "FROM rag_chunks WHERE namespace = ?",
                (namespace,),
            ).fetchone()
        return int(row[0]), float(row[1]), int(row[2])

    def _index_files(self, namespace: str) -> tuple[Path, Path]:
        key = hashlib.sha256(namespace.encode("utf-8")).hexdigest()
        return self.index_path / f"{key}.faiss", self.index_path / f"{key}.faiss.json"

    def _remove_index_files(self, namespace: str) -> None:
        self._index_cache.pop(namespace, None)
        for path in self._index_files(namespace):
            path.unlink(missing_ok=True)


def _normalized_matrix(vectors: Sequence[Sequence[float]]) -> np.ndarray:
    matrix = np.asarray(vectors, dtype="float32")
    if matrix.ndim != 2 or matrix.shape[0] < 1 or matrix.shape[1] < 1:
        raise ValueError("embedding vectors must form a non-empty matrix")
    faiss.normalize_L2(matrix)
    return np.ascontiguousarray(matrix)


def _embed_many(embedder: EmbeddingProvider, texts: Sequence[str]) -> list[Sequence[float]]:
    batch_method = getattr(embedder, "embed_many", None)
    if callable(batch_method):
        return list(batch_method(texts))
    return [embedder.embed(text) for text in texts]


def _metadata_owner(metadata_json: str) -> str | None:
    try:
        metadata = json.loads(metadata_json)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return str(metadata.get("owner_id")) if isinstance(metadata, dict) and metadata.get("owner_id") is not None else None


__all__ = ["FaissVectorStore"]
