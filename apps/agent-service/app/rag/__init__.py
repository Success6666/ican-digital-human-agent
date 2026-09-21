"""Retrieval augmented generation ports and adapters.

The package intentionally has no dependency on a particular vector database.
Docling, chunking and storage are replaceable through the protocols exported
here, while :class:`RagService` keeps the application-facing workflow stable.
"""

from .chunker import CharacterChunker, ChunkDraft, HierarchicalChunker
from .docling_parser import DoclingParser, DoclingRuntimeConfig, DocumentParseError
from .embeddings import HashEmbeddingProvider, LocalSentenceTransformerEmbeddingProvider
from .faiss_store import FaissVectorStore
from .limits import MetadataLimitError, MetadataLimits
from .memory_store import InMemoryVectorStore
from .models import (
    DocumentChunk,
    IngestRequest,
    IngestResult,
    ParsedDocument,
    SearchHit,
    SearchRequest,
    SearchResult,
)
from .service import RagService, build_default_rag_service
from .tuning import (
    QueryTrace,
    RetrievalOutcome,
    RetrievalTuning,
    classify_candidates,
    diagnose,
    retrieve,
    summarize_traces,
)

__all__ = [
    "CharacterChunker",
    "ChunkDraft",
    "DoclingParser",
    "DoclingRuntimeConfig",
    "DocumentChunk",
    "DocumentParseError",
    "FaissVectorStore",
    "HashEmbeddingProvider",
    "HierarchicalChunker",
    "InMemoryVectorStore",
    "IngestRequest",
    "IngestResult",
    "LocalSentenceTransformerEmbeddingProvider",
    "MetadataLimitError",
    "MetadataLimits",
    "ParsedDocument",
    "QueryTrace",
    "RagService",
    "RetrievalOutcome",
    "RetrievalTuning",
    "SearchHit",
    "SearchRequest",
    "SearchResult",
    "build_default_rag_service",
    "classify_candidates",
    "diagnose",
    "retrieve",
    "summarize_traces",
]
