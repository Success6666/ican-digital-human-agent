from __future__ import annotations

import asyncio

from app.rag.faiss_store import FaissVectorStore
from app.rag.models import DocumentChunk


class _KeywordEmbedding:
    dimensions = 3

    def embed(self, text: str) -> list[float]:
        return [
            1.0 if any(term in text for term in ("数字人", "语音", "播报")) else 0.0,
            1.0 if any(term in text for term in ("Docling", "PDF", "解析")) else 0.0,
            1.0 if any(term in text for term in ("FAISS", "项目")) else 0.0,
        ]


def _chunk(document_id: str, ordinal: int, text: str, *, owner: str = "owner-1", collection: str = "default") -> DocumentChunk:
    return DocumentChunk(
        chunk_id=f"{document_id}:{ordinal}",
        document_id=document_id,
        text=text,
        ordinal=ordinal,
        metadata={"owner_id": owner, "collection": collection},
    )


def test_faiss_store_persists_index_and_recovers_after_reopen(tmp_path) -> None:
    database = str(tmp_path / "rag.sqlite3")
    indexes = str(tmp_path / "faiss")

    async def scenario() -> None:
        first = FaissVectorStore(database, index_path=indexes, embedder=_KeywordEmbedding(), max_chunks=10)
        await first.upsert(
            [
                _chunk("doc-avatar", 0, "魔珐星云数字人支持实时语音播报"),
                _chunk("doc-rag", 0, "Docling 负责解析 PDF 文档并写入知识库"),
            ],
            namespace="ns-1",
        )
        assert list((tmp_path / "faiss").glob("*.faiss"))

        reopened = FaissVectorStore(database, index_path=indexes, embedder=_KeywordEmbedding(), max_chunks=10)
        hits = await reopened.search("数字人语音播报", namespace="ns-1", top_k=1)
        assert hits and hits[0].chunk.document_id == "doc-avatar"
        assert (await reopened.statistics(owner_id="owner-1")).documents == 2

        index_file = next((tmp_path / "faiss").glob("*.faiss"))
        index_file.write_bytes(b"broken-index")
        recovered = FaissVectorStore(database, index_path=indexes, embedder=_KeywordEmbedding(), max_chunks=10)
        recovered_hits = await recovered.search("PDF 文档解析", namespace="ns-1", top_k=1)
        assert recovered_hits and recovered_hits[0].chunk.document_id == "doc-rag"

    asyncio.run(scenario())


def test_faiss_store_filters_deletes_and_rebuilds_capacity(tmp_path) -> None:
    database = str(tmp_path / "rag.sqlite3")
    indexes = str(tmp_path / "faiss")

    async def scenario() -> None:
        store = FaissVectorStore(database, index_path=indexes, embedder=_KeywordEmbedding(), max_chunks=2)
        await store.upsert([_chunk("doc-a", 0, "默认集合的数字人文档")], namespace="ns-default")
        await store.upsert(
            [_chunk("doc-b", 0, "项目集合的 FAISS 文档", collection="project")],
            namespace="ns-project",
        )
        filtered = await store.search(
            "FAISS 文档",
            namespace="ns-project",
            metadata_filter={"collection": "project"},
        )
        assert filtered and filtered[0].chunk.document_id == "doc-b"
        assert await store.search("FAISS", namespace="ns-default")

        await store.upsert([_chunk("doc-c", 0, "新写入的数据触发全局容量淘汰")], namespace="ns-project")
        assert await store.count() == 2
        assert await store.search("默认集合", namespace="ns-default") == []
        assert await store.delete_document("doc-b", namespace="ns-project") == 1
        remaining = await store.search("FAISS 文档", namespace="ns-project")
        assert all(hit.chunk.document_id != "doc-b" for hit in remaining)

    asyncio.run(scenario())
