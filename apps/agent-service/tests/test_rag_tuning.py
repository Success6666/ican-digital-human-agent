"""Behavioural tests for the hybrid retrieval tuning pipeline."""

from __future__ import annotations

import asyncio

from app.rag.faiss_store import FaissVectorStore
from app.rag.models import DocumentChunk
from app.rag.tuning import (
    RetrievalTuning,
    bm25_rank,
    classify_candidates,
    contains_compatible_value,
    diagnose,
    fuse_positions,
    is_duplicate,
    parse_quantities,
    score_candidates,
    select_distinct,
    summarize_traces,
    tokens,
)


class _TermEmbedding:
    """Deterministic bag-of-terms embedder so dense ranking is predictable."""

    dimensions = 4
    _AXES = (("数字人", "语音", "播报"), ("Docling", "PDF", "解析"), ("FAISS", "向量", "索引"), ("额度", "计费", "价格"))

    def embed(self, text: str) -> list[float]:
        return [1.0 if any(term in text for term in axis) else 0.0 for axis in self._AXES]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


def _chunk(document_id: str, ordinal: int, text: str, *, owner: str = "owner-1", collection: str = "default") -> DocumentChunk:
    return DocumentChunk(
        chunk_id=f"{document_id}:{ordinal}",
        document_id=document_id,
        text=text,
        ordinal=ordinal,
        metadata={"owner_id": owner, "collection": collection},
    )


def test_bm25_ranks_rare_terms_above_common_ones() -> None:
    documents = [
        "系统支持数字人播报功能",
        "系统支持数字人播报功能与更多说明",
        "计费额度独立管理",
    ]
    ranked = bm25_rank("计费额度", documents, top_n=2)
    assert ranked, "expected at least one lexical match"
    assert documents[ranked[0][0]] == "计费额度独立管理"


def test_bm25_drops_zero_score_documents() -> None:
    assert bm25_rank("完全无关的词汇", ["数字人播报", "Docling 解析"], top_n=5) == []


def test_reciprocal_rank_fusion_prefers_documents_present_in_both_routes() -> None:
    # Position 3 is ranked second by both routes; positions 0 and 1 lead one
    # route each. RRF must lift the agreed-on document above both.
    fused = fuse_positions([[0, 3], [1, 3]], k=60.0)
    assert fused[0][0] == 3


def test_fusion_deduplicates_within_one_route_and_is_deterministic() -> None:
    first = fuse_positions([[2, 2, 0, 1]], k=60.0)
    second = fuse_positions([[2, 2, 0, 1]], k=60.0)
    assert first == second
    assert [position for position, _ in first] == [2, 0, 1]


def test_tokenizer_keeps_ascii_identifiers_whole() -> None:
    assert "bge-small-zh-v1.5" in tokens("模型 bge-small-zh-v1.5 可用")


def test_near_duplicate_detection_and_short_text_exemption() -> None:
    long_a = "本项目支持 4K 超高清视频输出，帧率可达 60fps，满足直播场景需求。"
    long_b = "本项目支持 4K 超高清视频输出，帧率可达 60fps，满足直播场景的需求。"
    assert is_duplicate(long_a, long_b, threshold=0.8)
    # Short identifiers are frequently legitimately identical (part numbers,
    # error codes) so they must survive suppression.
    assert not is_duplicate("编号 8848", "编号 8848", threshold=0.8, short_text_chars=24)


def test_select_distinct_suppresses_duplicate_and_refills_from_pool() -> None:
    from app.rag.tuning import Candidate

    pool = [
        Candidate(position=0, text="本项目支持 4K 超高清视频输出，帧率可达 60fps。", score=0.9),
        Candidate(position=1, text="本项目支持 4K 超高清视频输出，帧率可达 60fps。", score=0.85),
        Candidate(position=2, text="音频采样率为 48kHz，支持双声道输出。", score=0.8),
    ]
    selected = select_distinct(pool, limit=2, redundancy_threshold=0.8, short_text_chars=24)
    assert [candidate.position for candidate in selected] == [0, 2]


def test_quantity_parsing_and_four_valued_comparison() -> None:
    quantities = parse_quantities("输出 4K，帧率 60fps")
    assert quantities, "expected numeric expectations"
    assert contains_compatible_value("支持 4K 输出吗", "分辨率支持 3840x2160 输出")
    assert contains_compatible_value("帧率 60fps", "帧率可达 60 fps")
    # A contradiction must not be accepted as corroboration.
    assert not contains_compatible_value("支持 4K 输出吗", "仅支持 1080p 输出")
    # 10% apart with a 5% default tolerance is a conflict, and stays configurable.
    assert not contains_compatible_value("延迟 200ms", "延迟 180ms")
    assert contains_compatible_value("延迟 200ms", "延迟 180ms", relative_tolerance=0.15)


def test_scoring_prefers_lexical_agreement_at_equal_fusion_rank() -> None:
    scored = score_candidates(
        query="4K 分辨率",
        texts=["分辨率支持 4K 输出", "音频采样率 48kHz"],
        positions=[0, 1],
        fusion_scores=[1.0, 1.0],
    )
    assert scored[0].position == 0


def test_trace_buckets_are_mutually_exclusive() -> None:
    counts = classify_candidates(
        positions=[0, 1, 2, 3, 4],
        fused_positions=[0, 1, 2],
        filtered_positions=[0, 1],
        selected_positions=[0],
        final_limit=1,
    )
    assert counts["selected"] == 1
    assert counts["dropped_in_fusion"] == 2
    assert counts["filtered_out"] == 1
    assert counts["rank_too_low"] == 1
    assert sum(counts.values()) == 5


def test_store_search_traces_the_pipeline(tmp_path) -> None:
    async def scenario() -> None:
        store = FaissVectorStore(
            str(tmp_path / "rag.sqlite3"),
            index_path=str(tmp_path / "faiss"),
            embedder=_TermEmbedding(),
            max_chunks=10,
            tuning=RetrievalTuning(),
        )
        await store.upsert(
            [
                _chunk("doc-avatar", 0, "数字人支持实时语音播报"),
                _chunk("doc-rag", 0, "Docling 负责解析 PDF 文档"),
                _chunk("doc-billing", 0, "计费额度独立管理"),
            ],
            namespace="ns-1",
        )
        hits, trace = await store.search_traced("计费额度", namespace="ns-1", top_k=2)
        assert hits and hits[0].chunk.document_id == "doc-billing"
        assert trace is not None
        assert trace.query == "计费额度"
        assert trace.namespace == "ns-1"
        assert trace.candidates_selected == len(hits)
        assert trace.routes and {route.name for route in trace.routes} >= {"vector"}
        assert diagnose([trace]).startswith("1 queries")

    asyncio.run(scenario())


def test_store_lexical_route_recovers_document_the_vector_route_misses(tmp_path) -> None:
    """BM25 exists to catch exact terms the dense route scores weakly."""

    async def scenario() -> None:
        store = FaissVectorStore(
            str(tmp_path / "rag.sqlite3"),
            index_path=str(tmp_path / "faiss"),
            embedder=_TermEmbedding(),
            max_chunks=10,
        )
        await store.upsert(
            [
                _chunk("doc-avatar", 0, "数字人支持实时语音播报"),
                _chunk("doc-misc", 0, "内部工具链说明文档"),
            ],
            namespace="ns-1",
        )
        # "工具链" shares no embedding axis with the query, so only the lexical
        # route can surface it.
        hits = await store.search("工具链", namespace="ns-1", top_k=2)
        assert any(hit.chunk.document_id == "doc-misc" for hit in hits)

    asyncio.run(scenario())


def test_store_metadata_filter_restricts_eligibility_before_ranking(tmp_path) -> None:
    async def scenario() -> None:
        store = FaissVectorStore(
            str(tmp_path / "rag.sqlite3"),
            index_path=str(tmp_path / "faiss"),
            embedder=_TermEmbedding(),
            max_chunks=10,
        )
        await store.upsert(
            [
                _chunk("doc-default", 0, "默认集合的数字人文档"),
                _chunk("doc-project", 0, "项目集合的 FAISS 文档", collection="project"),
            ],
            namespace="ns-1",
        )
        hits = await store.search(
            "FAISS 文档",
            namespace="ns-1",
            top_k=5,
            metadata_filter={"collection": "project"},
        )
        assert [hit.chunk.document_id for hit in hits] == ["doc-project"]

    asyncio.run(scenario())


def test_tuning_can_be_disabled_per_stage() -> None:
    tuning = RetrievalTuning(lexical_enabled=False, numeric_boost_enabled=False, redundancy_threshold=1.1)
    assert tuning.lexical_enabled is False
    overridden = tuning.with_overrides(lexical_enabled=True)
    assert overridden.lexical_enabled is True
    # Frozen dataclass: the original must be untouched.
    assert tuning.lexical_enabled is False


def test_tuning_reads_the_environment() -> None:
    tuning = RetrievalTuning.from_env(
        {
            "RAG_LEXICAL_ENABLED": "false",
            "RAG_RRF_K": "42",
            "RAG_LEXICAL_TOP_K": "12",
            "RAG_REDUNDANCY_THRESHOLD": "0.9",
        }
    )
    assert tuning.lexical_enabled is False
    assert tuning.rrf_k == 42.0
    assert tuning.lexical_route_top_k == 12
    assert tuning.redundancy_threshold == 0.9
    # Invalid values fall back to the defaults rather than raising at import.
    assert RetrievalTuning.from_env({"RAG_RRF_K": "not-a-number"}).rrf_k == 60.0


def test_summarize_traces_aggregates_bucket_shares() -> None:
    from app.rag.tuning import QueryTrace

    trace = QueryTrace(query="q", namespace="ns")
    trace.record("selected", count=3)
    trace.record("rank_too_low", count=1)
    summary = summarize_traces([trace])
    assert summary["queries"] == 1
    assert summary["totals"]["selected"] == 3
    assert summary["shares"]["selected"] == 0.75
