"""Internal APIs for the interview training workflow."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status

from ..api.dependencies import InternalContext, require_internal_context
from ..rag.models import IngestRequest
from ..rag.docling_parser import DocumentParseError
from ..webfetch import FetchError, WebFetchService
from .models import (
    CreateInterviewRequest,
    InterviewEvaluation,
    InterviewSession,
    InterviewTurnRequest,
    InterviewTurnResponse,
)
from .service import InterviewService


def build_router(*, interview: InterviewService, rag: Any, webfetch: WebFetchService) -> APIRouter:
    api = APIRouter(
        prefix="/internal/interviews",
        tags=["interviews"],
        dependencies=[Depends(require_internal_context)],
    )

    @api.post("", response_model=InterviewSession, status_code=status.HTTP_201_CREATED)
    async def create(payload: CreateInterviewRequest, context: InternalContext) -> InterviewSession:
        return await interview.create(context["user_id"], payload)

    @api.post("/{session_id}/turn", response_model=InterviewTurnResponse)
    async def turn(
        session_id: str,
        payload: InterviewTurnRequest,
        context: InternalContext,
    ) -> InterviewTurnResponse:
        try:
            return await interview.turn(context["user_id"], session_id, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="interview session not found") from exc

    @api.post("/{session_id}/evaluation", response_model=InterviewEvaluation)
    async def evaluation(session_id: str, context: InternalContext) -> InterviewEvaluation:
        try:
            return await interview.evaluate(context["user_id"], session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="interview session not found") from exc

    @api.post("/sources/jd")
    async def import_jd(url: str, context: InternalContext) -> dict[str, Any]:
        try:
            fetched = await webfetch.fetch(url)
        except FetchError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        state = webfetch.change_state(context["user_id"], fetched)
        if state == "unchanged":
            return {"status": state, "url": fetched.url, "content_hash": fetched.content_hash}
        result = await rag.ingest(
            IngestRequest(
                source_name=fetched.url,
                content=fetched.text,
                content_type="text/plain",
                collection="interview",
                metadata={
                    "document_type": "job_description",
                    "source_url": fetched.url,
                    "content_hash": fetched.content_hash,
                    "update_state": state,
                    "company": _extract_company(fetched.title, fetched.text),
                },
            ),
            owner_id=context["user_id"],
        )
        return {"status": state, "url": fetched.url, "content_hash": fetched.content_hash, "document": result}

    @api.post("/sources/company")
    async def import_company(company: str, context: InternalContext) -> dict[str, Any]:
        try:
            fetched = await webfetch.search_company(company)
        except FetchError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        state = webfetch.change_state(context["user_id"], fetched)
        if state == "unchanged":
            return {"status": state, "url": fetched.url, "content_hash": fetched.content_hash}
        result = await rag.ingest(
            IngestRequest(
                source_name=fetched.url,
                content=fetched.text,
                content_type="text/plain",
                collection="interview",
                metadata={
                    "document_type": "company_background",
                    "source_url": fetched.url,
                    "content_hash": fetched.content_hash,
                    "update_state": state,
                    "company": company[:200],
                },
            ),
            owner_id=context["user_id"],
        )
        return {"status": state, "url": fetched.url, "content_hash": fetched.content_hash, "document": result}

    @api.post("/sources/resume")
    async def import_resume(
        context: InternalContext,
        file: UploadFile = File(...),
    ) -> dict[str, Any]:
        payload = await file.read(rag.max_document_bytes + 1)
        if len(payload) > rag.max_document_bytes:
            raise HTTPException(status_code=413, detail="resume exceeds configured size limit")
        if not file.filename:
            raise HTTPException(status_code=400, detail="resume filename is required")
        try:
            result = await rag.ingest(
                IngestRequest(
                    source_name=file.filename,
                    content_base64=_encode(payload),
                    content_type=file.content_type,
                    collection="interview",
                    metadata={"document_type": "resume"},
                ),
                owner_id=context["user_id"],
            )
        except (DocumentParseError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="resume parsing failed") from exc
        return {"document": result}

    return api


def _extract_company(title: str, text: str) -> str:
    for marker in ("公司", "企业"):
        if marker in title:
            return title[:120]
    return text[:120]


def _encode(payload: bytes) -> str:
    import base64

    return base64.b64encode(payload).decode("ascii")
