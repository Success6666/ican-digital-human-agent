"""Optional FastAPI routes for the RAG module."""

from __future__ import annotations

import json
from typing import Any

from .docling_parser import DocumentParseError
from .models import IngestRequest, IngestResult, SearchRequest, SearchResult
from .service import RagService, build_default_rag_service
from ..observability.redaction import redact_text

try:  # Keep importing the package possible for non-HTTP workers.
    from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
except ImportError:  # pragma: no cover - exercised only in minimal workers
    APIRouter = None  # type: ignore[assignment,misc]
    Depends = HTTPException = UploadFile = File = Query = None  # type: ignore[assignment]

try:
    from app.api.dependencies import InternalContext
except ImportError:  # pragma: no cover - standalone package import
    InternalContext = Any  # type: ignore[assignment,misc]


def _auth_dependency():
    """Reuse the agent auth dependency, with a safe standalone fallback."""

    try:
        from app.api.dependencies import require_internal_context

        return require_internal_context
    except ImportError:
        async def require_internal_context(request: Any, x_internal_token: str | None = None):
            del request
            import os

            expected = os.getenv("AGENT_INTERNAL_TOKEN", "dev-agent-internal-token")
            if not x_internal_token or x_internal_token != expected:
                raise HTTPException(status_code=401, detail="unauthorized")
            return {"user_id": "system", "user_name": "system"}

        return require_internal_context


_service: RagService | None = None


def get_rag_service() -> RagService:
    global _service
    if _service is None:
        observer = None
        try:
            from app.observability.service import get_observability

            observer = get_observability()
        except Exception:
            pass
        _service = build_default_rag_service(observer=observer)
    return _service


def set_rag_service(service: RagService) -> None:
    """Replace the singleton in tests or at application startup."""

    global _service
    _service = service


def build_router(service: RagService | None = None, *, prefix: str = "/internal/rag"):
    if APIRouter is None:
        return None
    selected = service or get_rag_service()
    api = APIRouter(prefix=prefix, tags=["rag"], dependencies=[Depends(_auth_dependency())])

    @api.get("/health")
    async def health() -> dict[str, Any]:
        count = await selected.count()
        parser = getattr(selected.parser, "available", None)
        return {
            "status": "ok",
            "documents": count,
            "docling_available": parser,
            "docling_loaded": bool(getattr(selected.parser, "loaded", False)),
            "docling_load_error": getattr(selected.parser, "load_error", None),
            "parse_concurrency": selected.parse_concurrency,
        }

    @api.post("/ingest", response_model=IngestResult)
    async def ingest(request: IngestRequest, context: InternalContext) -> IngestResult:
        try:
            return await selected.ingest(request, owner_id=context["user_id"])
        except (DocumentParseError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=_public_error(exc)) from exc

    @api.post("/ingest/file", response_model=IngestResult)
    async def ingest_file(
        context: InternalContext,
        file: UploadFile = File(...),
        collection: str = Query(default="default", min_length=1, max_length=128),
        metadata: str | None = Query(default=None),
    ) -> IngestResult:
        raw_metadata: dict[str, Any] = {}
        if metadata:
            if len(metadata.encode("utf-8")) > selected.metadata_limits.max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"metadata exceeds {selected.metadata_limits.max_bytes} bytes",
                )
            try:
                parsed_metadata = json.loads(metadata)
                if not isinstance(parsed_metadata, dict):
                    raise ValueError("metadata must be a JSON object")
                raw_metadata = parsed_metadata
            except (json.JSONDecodeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail="metadata must be valid JSON object") from exc
        payload = await file.read(selected.max_document_bytes + 1)
        if len(payload) > selected.max_document_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"document exceeds {selected.max_document_bytes} bytes",
            )
        request = IngestRequest(
            source_name=file.filename or "upload.bin",
            content_base64=_encode(payload),
            content_type=file.content_type,
            collection=collection,
            metadata=raw_metadata,
        )
        try:
            return await selected.ingest(request, owner_id=context["user_id"])
        except (DocumentParseError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=_public_error(exc)) from exc

    @api.post("/search", response_model=SearchResult)
    async def search(request: SearchRequest, context: InternalContext) -> SearchResult:
        return await selected.search(request, owner_id=context["user_id"])

    @api.delete("/documents/{document_id}")
    async def delete_document(
        document_id: str,
        context: InternalContext,
        collection: str = Query(default="default", min_length=1, max_length=128),
    ) -> dict[str, Any]:
        deleted = await selected.delete(document_id, owner_id=context["user_id"], collection=collection)
        return {"document_id": document_id, "deleted_chunks": deleted}

    return api


def _encode(payload: bytes) -> str:
    import base64

    return base64.b64encode(payload).decode("ascii")


def _public_error(exc: Exception) -> str:
    """Keep document diagnostics useful without reflecting user-controlled data."""

    raw = str(exc).strip()
    message = raw.splitlines()[0] if raw else exc.__class__.__name__
    return redact_text(message, max_length=300) or exc.__class__.__name__


router = build_router()

__all__ = ["build_router", "get_rag_service", "router", "set_rag_service"]
