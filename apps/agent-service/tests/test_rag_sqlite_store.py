from __future__ import annotations

import asyncio

from app.rag.models import DocumentChunk
from app.rag.sqlite_store import SqliteVectorStore


def _chunk(document_id: str, ordinal: int, text: str, owner: str = "owner-1") -> DocumentChunk:
    return DocumentChunk(
        chunk_id=f"{document_id}:{ordinal}",
        document_id=document_id,
        text=text,
        ordinal=ordinal,
        metadata={"owner_id": owner, "collection": "default"},
    )


def test_sqlite_store_survives_reopen_and_delete(tmp_path) -> None:
    path = str(tmp_path / "rag.sqlite3")

    async def scenario() -> None:
        first = SqliteVectorStore(path, max_chunks=10)
        await first.upsert([_chunk("doc-1", 0, "星云数字人接入说明")], namespace="ns-1")
        reopened = SqliteVectorStore(path, max_chunks=10)
        hits = await reopened.search("星云数字人", namespace="ns-1")
        assert hits and hits[0].chunk.document_id == "doc-1"
        assert (await reopened.statistics(owner_id="owner-1")).documents == 1
        assert await reopened.delete_document("doc-1", namespace="ns-1") == 1
        assert await SqliteVectorStore(path).search("星云数字人", namespace="ns-1") == []

    asyncio.run(scenario())


def test_sqlite_store_keeps_namespaces_isolated_and_bounds_capacity(tmp_path) -> None:
    path = str(tmp_path / "rag.sqlite3")

    async def scenario() -> None:
        store = SqliteVectorStore(path, max_chunks=1)
        await store.upsert([_chunk("doc-a", 0, "甲集合内容")], namespace="ns-a")
        await store.upsert([_chunk("doc-b", 0, "乙集合内容")], namespace="ns-b")
        assert await store.count() == 1
        assert await store.search("甲集合", namespace="ns-a") == []
        assert (await store.search("乙集合", namespace="ns-b"))[0].chunk.document_id == "doc-b"

    asyncio.run(scenario())
