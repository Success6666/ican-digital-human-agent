"""FAISS vector index with SQLite-backed document metadata and recovery."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Any

import faiss
import numpy as np

from .embeddings import HashEmbeddingProvider
from .memory_store import _matches
from .models import CollectionStatistics, DocumentChunk, RagStatistics, SearchHit
from .ports import EmbeddingProvider


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
    ) -> None:
        if not path.strip():
            raise ValueError("path is required")
        if max_chunks < 1:
            raise ValueError("max_chunks must be positive")
        self.path = Path(path)
        self.index_path = Path(index_path) if index_path else self.path.with_suffix(".faiss")
        self.embedder = embedder or HashEmbeddingProvider()
        self.max_chunks = max_chunks
        self._write_lock = asyncio.Lock()
        self._index_cache: dict[str, tuple[tuple[int, float, int], faiss.Index]] = {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.index_path.mkdir(parents=True, exist_ok=True)
        self._initialize()

    async def upsert(self, chunks: Sequence[DocumentChunk], *, namespace: str) -> None:
        if not namespace:
            raise ValueError("namespace is required")
        prepared = [
            (namespace, chunk, await asyncio.to_thread(self.embedder.embed, chunk.text))
            for chunk in chunks
        ]
        async with self._write_lock:
            await asyncio.to_thread(self._upsert_sync, prepared)
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
            namespace,
            top_k,
            metadata_filter or {},
        )

    async def delete_document(self, document_id: str, *, namespace: str) -> int:
        async with self._write_lock:
            deleted = await asyncio.to_thread(self._delete_sync, document_id, namespace)
            if deleted:
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
        namespace: str,
        top_k: int,
        metadata_filter: dict[str, Any],
    ) -> list[SearchHit]:
        rows = self._read_namespace(namespace)
        if not rows:
            return []
        query = _normalized_matrix([query_vector])
        index = self._load_index_sync(namespace, rows, expected_dimensions=query.shape[1])
        search_count = len(rows) if metadata_filter else min(len(rows), max(top_k * 4, top_k))
        scores, positions = index.search(query, search_count)
        hits: list[SearchHit] = []
        for score, position in zip(scores[0].tolist(), positions[0].tolist(), strict=True):
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
                    score=round(float(score), 8),
                )
            )
            if len(hits) >= top_k:
                break
        return hits

    def _load_index_sync(
        self,
        namespace: str,
        rows: list[tuple[Any, ...]],
        *,
        expected_dimensions: int,
    ) -> faiss.Index:
        signature = self._signature(namespace)
        cached = self._index_cache.get(namespace)
        if cached and cached[0] == signature and cached[1].d == expected_dimensions:
            return cached[1]
        index_file, signature_file = self._index_files(namespace)
        try:
            stored_signature = tuple(json.loads(signature_file.read_text(encoding="utf-8")))
            index = faiss.read_index(str(index_file))
            if stored_signature == signature and index.ntotal == len(rows) and index.d == expected_dimensions:
                self._index_cache[namespace] = (signature, index)
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
        index = faiss.IndexFlatIP(matrix.shape[1])
        index.add(matrix)
        self._persist_index(namespace, index, self._signature(namespace))
        self._index_cache[namespace] = (self._signature(namespace), index)
        return index

    def _persist_index(self, namespace: str, index: faiss.Index, signature: tuple[int, float, int]) -> None:
        index_file, signature_file = self._index_files(namespace)
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


def _metadata_owner(metadata_json: str) -> str | None:
    try:
        metadata = json.loads(metadata_json)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return str(metadata.get("owner_id")) if isinstance(metadata, dict) and metadata.get("owner_id") is not None else None


__all__ = ["FaissVectorStore"]
