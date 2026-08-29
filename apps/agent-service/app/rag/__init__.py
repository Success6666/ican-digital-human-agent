"""Retrieval augmented generation ports and adapters.

The package intentionally has no dependency on a particular vector database.
Docling, chunking and storage are replaceable through the protocols exported
here, while :class:`RagService` keeps the application-facing workflow stable.
"""

from .chunker import CharacterChunker
from .docling_parser import DocumentParseError, DoclingParser, DoclingRuntimeConfig
from .embeddings import HashEmbeddingProvider
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

__all__ = [
    "CharacterChunker",
    "DocumentChunk",
    "DocumentParseError",
    "DoclingParser",
    "DoclingRuntimeConfig",
    "HashEmbeddingProvider",
    "InMemoryVectorStore",
    "IngestRequest",
    "IngestResult",
    "MetadataLimitError",
    "MetadataLimits",
    "ParsedDocument",
    "RagService",
    "SearchHit",
    "SearchRequest",
    "SearchResult",
    "build_default_rag_service",
]
