"""SQLite-backed vector storage for durable RAG collections."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
import json
from pathlib import Path
import sqlite3
import time
from typing import Any

from .embeddings import HashEmbeddingProvider
from .memory_store import _cosine, _matches
from .models import CollectionStatistics, DocumentChunk, RagStatistics, SearchHit
from .ports import EmbeddingProvider


class SqliteVectorStore:
    """Durable vector store using SQLite metadata and deterministic vectors."""

    def __init__(
        self,
        path: str,
        *,
        embedder: EmbeddingProvider | None = None,
        max_chunks: int = 10_000,
    ) -> None:
        if not path.strip():
            raise ValueError("path is required")
        if max_chunks < 1:
            raise ValueError("max_chunks must be positive")
        self.path = Path(path)
        self.embedder = embedder or HashEmbeddingProvider()
        self.max_chunks = max_chunks
        self._write_lock = asyncio.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
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
        rows = await asyncio.to_thread(self._read_namespace, namespace)
        expected = metadata_filter or {}
        hits: list[SearchHit] = []
        for text, document_id, chunk_id, ordinal, metadata_json, vector_json in rows:
            try:
                metadata = json.loads(metadata_json)
                vector = json.loads(vector_json)
                if not isinstance(metadata, dict) or not isinstance(vector, list) or not _matches(metadata, expected):
                    continue
                chunk = DocumentChunk(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    text=text,
                    ordinal=ordinal,
                    metadata=metadata,
                )
                hits.append(SearchHit(chunk=chunk, score=round(_cosine(query_vector, vector), 8)))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        hits.sort(key=lambda hit: (-hit.score, hit.chunk.ordinal, hit.chunk.chunk_id))
        return hits[:top_k]

    async def delete_document(self, document_id: str, *, namespace: str) -> int:
        async with self._write_lock:
            return await asyncio.to_thread(self._delete_sync, document_id, namespace)

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

    def _read_namespace(self, namespace: str) -> list[tuple[Any, ...]]:
        with self._connect() as connection:
            return connection.execute(
                "SELECT text, document_id, chunk_id, ordinal, metadata_json, vector_json FROM rag_chunks WHERE namespace = ?",
                (namespace,),
            ).fetchall()

    def _owner_rows(self, owner_id: str) -> list[tuple[str, str]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT document_id, metadata_json FROM rag_chunks").fetchall()
        result: list[tuple[str, str]] = []
        for document_id, metadata_json in rows:
            try:
                metadata = json.loads(metadata_json)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(metadata, dict) and metadata.get("owner_id") == owner_id:
                result.append((document_id, metadata_json))
        return result

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


__all__ = ["SqliteVectorStore"]
