"""Retrieval augmented generation ports and adapters.

The package intentionally has no dependency on a particular vector database.
Docling, chunking and storage are replaceable through the protocols exported
here, while :class:`RagService` keeps the application-facing workflow stable.
"""

from .chunker import CharacterChunker, ChunkDraft, HierarchicalChunker
from .docling_parser import DocumentParseError, DoclingParser, DoclingRuntimeConfig
from .embeddings import HashEmbeddingProvider, LocalSentenceTransformerEmbeddingProvider
from .faiss_store import FaissVectorStore
from .memory_store import InMemoryVectorStore
from .limits import MetadataLimitError, MetadataLimits
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
    RetrievalOutcome,
    RetrievalTuning,
    QueryTrace,
    classify_candidates,
    diagnose,
    retrieve,
    summarize_traces,
)

__all__ = [
    "CharacterChunker",
    "ChunkDraft",
    "HierarchicalChunker",
    "DocumentChunk",
    "DocumentParseError",
    "DoclingParser",
    "DoclingRuntimeConfig",
    "HashEmbeddingProvider",
    "FaissVectorStore",
    "LocalSentenceTransformerEmbeddingProvider",
    "InMemoryVectorStore",
    "IngestRequest",
    "IngestResult",
    "MetadataLimitError",
    "MetadataLimits",
    "ParsedDocument",
    "RagService",
    "QueryTrace",
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
