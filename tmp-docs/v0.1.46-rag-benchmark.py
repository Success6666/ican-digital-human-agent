"""可重复的 RAG 热路径基准与 Recall@K/MRR 评测。"""

from __future__ import annotations

import asyncio
import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "apps" / "agent-service"
sys.path.insert(0, str(SERVICE))

from app.rag.chunker import HierarchicalChunker  # noqa: E402
from app.rag.embeddings import HashEmbeddingProvider, LocalSentenceTransformerEmbeddingProvider  # noqa: E402
from app.rag.faiss_store import FaissVectorStore  # noqa: E402
from app.rag.models import DocumentChunk  # noqa: E402
from app.rag.service import RagService  # noqa: E402
from app.rag.docling_parser import DoclingParser, DoclingRuntimeConfig  # noqa: E402


def _docs() -> list[tuple[str, str, str]]:
    topics = [
        ("voice", "数字人支持中文实时语音播报，麦克风输入采用 16kHz PCM16 单声道。"),
        ("rag", "RAG 文档需要经过解析、父子分块、向量化和 FAISS 检索，回答必须引用来源。"),
        ("tenant", "多租户知识库按账号和集合隔离，租户之间不能召回彼此的私有文档。"),
        ("cache", "答案缓存使用 TTL 和最大条目数，命中后重置过期时间，避免内存无限增长。"),
        ("avatar", "数字人连接完成后保持会话缓存，切换页面不重新创建渲染实例。"),
    ]
    return [(f"doc-{name}-{i}", name, f"# {name}\n\n{text}\n\n补充说明：该知识条目用于 RAG 召回准确率测试。" * 4) for i, (name, text) in enumerate(topics)]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RAG 热路径与召回基准")
    parser.add_argument(
        "--embedding",
        choices=("local", "hash"),
        default="local",
        help="默认使用本机 BGE；hash 仅用于显式离线对照",
    )
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()
    root = ROOT / "tmp-docs" / "rag-evaluations"
    root.mkdir(parents=True, exist_ok=True)
    # FAISS on Windows has trouble opening wide-character absolute paths;
    # keep benchmark paths relative while production containers use Linux.
    db = Path("tmp-docs/rag-evaluations/benchmark.sqlite3")
    indexes = Path("tmp-docs/rag-evaluations/benchmark-faiss")
    for path in (db,):
        path.unlink(missing_ok=True)
    for path in indexes.glob("*"):
        path.unlink(missing_ok=True)
    indexes.mkdir(parents=True, exist_ok=True)

    if args.embedding == "local":
        embedder = LocalSentenceTransformerEmbeddingProvider(
            model="BAAI/bge-small-zh-v1.5",
            dimensions=512,
            device="auto",
            cache_dir="tmp-docs/rag-evaluations/model-cache",
            batch_size=64,
        )
    else:
        embedder = HashEmbeddingProvider(dimensions=256)
    store = FaissVectorStore(str(db), index_path=str(indexes), embedder=embedder, max_chunks=10_000, hnsw_min_chunks=999999)
    service = RagService(
        parser=DoclingParser(config=DoclingRuntimeConfig(enabled=False)),
        chunker=HierarchicalChunker(max_chars=220, overlap_chars=24, parent_max_chars=700, parent_overlap_chars=80),
        store=store,
        search_cache_ttl_seconds=30,
        search_cache_max_entries=128,
    )
    for document_id, collection, content in _docs():
        from app.rag.models import IngestRequest
        await service.ingest(IngestRequest(document_id=document_id, source_name=f"{collection}.md", content=content, collection="default"), owner_id="bench")

    queries = [("语音播报", "doc-voice-0"), ("父子分块 FAISS", "doc-rag-1"), ("租户隔离", "doc-tenant-2"), ("缓存 TTL", "doc-cache-3"), ("页面数字人会话", "doc-avatar-4")]
    cold: list[float] = []
    warm: list[float] = []
    hit_ranks: list[int] = []
    for query, expected in queries:
        started = time.perf_counter()
        result = await service.search(__import__("app.rag.models", fromlist=["SearchRequest"]).SearchRequest(query=query, top_k=5), owner_id="bench")
        cold.append((time.perf_counter() - started) * 1000)
        rank = next((index + 1 for index, hit in enumerate(result.hits) if hit.chunk.document_id == expected), None)
        if rank:
            hit_ranks.append(rank)
        started = time.perf_counter()
        await service.search(__import__("app.rag.models", fromlist=["SearchRequest"]).SearchRequest(query=query, top_k=5), owner_id="bench")
        warm.append((time.perf_counter() - started) * 1000)

    recall = len(hit_ranks) / len(queries)
    mrr = statistics.mean([1 / rank for rank in hit_ranks]) if hit_ranks else 0.0
    result = {
        "version": "0.1.46",
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "documents": len(_docs()),
        "embedding": args.embedding,
        "embeddingModel": getattr(embedder, "model_name", embedder.__class__.__name__),
        "embeddingDimensions": embedder.dimensions,
        "resolvedDevice": getattr(embedder, "resolved_device", "n/a"),
        "chunks": await store.count(),
        "metrics": {
            "recallAt5": round(recall, 4),
            "mrr": round(mrr, 4),
            "coldP50Ms": round(statistics.median(cold), 3),
            "coldP95Ms": round(sorted(cold)[max(0, int(len(cold) * 0.95) - 1)], 3),
            "warmCacheP50Ms": round(statistics.median(warm), 3),
            "warmCacheP95Ms": round(sorted(warm)[max(0, int(len(warm) * 0.95) - 1)], 3),
        },
        "raw": {"queries": queries, "coldMs": cold, "warmCacheMs": warm, "hitRanks": hit_ranks},
    }
    output = root / f"v0.1.46-{args.embedding}-hierarchical-cache.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
