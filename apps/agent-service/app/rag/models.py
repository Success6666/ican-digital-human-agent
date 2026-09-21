"""RAG domain and HTTP boundary models."""

from __future__ import annotations

import base64
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .limits import MetadataLimits, max_base64_chars, validate_metadata


class ParsedDocument(BaseModel):
    """Normalized output from a document parser."""

    model_config = ConfigDict(extra="forbid")

    document_id: str
    source_name: str
    content: str
    content_type: str = "text/plain"
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentChunk(BaseModel):
    """A searchable, source-aware piece of a document."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    document_id: str
    text: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchHit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk: DocumentChunk
    score: float


class SearchResult(BaseModel):
    query: str
    collection: str
    hits: list[SearchHit] = Field(default_factory=list)


class CollectionStatistics(BaseModel):
    name: str
    documents: int = Field(ge=0)
    chunks: int = Field(ge=0)


class RagStatistics(BaseModel):
    documents: int = Field(ge=0)
    chunks: int = Field(ge=0)
    collections: list[CollectionStatistics] = Field(default_factory=list)


class IngestRequest(BaseModel):
    """JSON-friendly ingest request.

    ``content`` is UTF-8 text for Markdown/HTML/plain text. Binary documents
    may be sent in ``content_base64``; exactly one content field is required.
    """

    model_config = ConfigDict(extra="forbid")

    source_name: str = Field(min_length=1, max_length=512)
    content: str | None = None
    content_base64: str | None = None
    content_type: str | None = Field(default=None, max_length=128)
    document_id: str | None = Field(default=None, max_length=128)
    collection: str = Field(default="default", min_length=1, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_content(self) -> IngestRequest:
        if (self.content is None) == (self.content_base64 is None):
            raise ValueError("exactly one of content or content_base64 is required")
        return self

    def payload(self, *, max_bytes: int | None = None) -> bytes:
        """Decode content after applying a cheap encoded-length precheck."""

        if max_bytes is not None and max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if self.content_base64 is not None:
            if max_bytes is not None and len(self.content_base64) > max_base64_chars(max_bytes):
                raise ValueError(f"document exceeds {max_bytes} bytes")
            try:
                payload = base64.b64decode(self.content_base64, validate=True)
            except (ValueError, base64.binascii.Error) as exc:
                raise ValueError("content_base64 is not valid base64") from exc
            if max_bytes is not None and len(payload) > max_bytes:
                raise ValueError(f"document exceeds {max_bytes} bytes")
            return payload

        content = self.content or ""
        if max_bytes is not None and len(content) > max_bytes:
            raise ValueError(f"document exceeds {max_bytes} bytes")
        encoded = bytearray()
        # Avoid allocating a potentially huge UTF-8 buffer in one shot.
        for offset in range(0, len(content), 4096):
            encoded.extend(content[offset : offset + 4096].encode("utf-8"))
            if max_bytes is not None and len(encoded) > max_bytes:
                raise ValueError(f"document exceeds {max_bytes} bytes")
        return bytes(encoded)

    def validate_metadata(self, limits: MetadataLimits) -> None:
        validate_metadata(self.metadata, limits)


class IngestResult(BaseModel):
    document_id: str
    source_name: str
    collection: str
    parser: str
    chunk_count: int = Field(ge=0)


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=4000)
    collection: str = Field(default="default", min_length=1, max_length=128)
    top_k: int = Field(default=5, ge=1, le=50)
    metadata_filter: dict[str, Any] = Field(default_factory=dict)

    def validate_metadata(self, limits: MetadataLimits) -> None:
        validate_metadata(self.metadata_filter, limits)
