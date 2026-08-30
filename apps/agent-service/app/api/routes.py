"""Internal FastAPI routes; the auth service is the only public caller."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from ..application.errors import ApplicationError
from ..domain.models import AvatarSession, ChatResult
from .client_params import browser_safe_client_params
from .dependencies import InternalContext, get_container
from .sse import iter_sse_frames
from .schemas import (
    ChatRequest,
    ChatResponse,
    ConfigurationPatch,
    CreateSessionRequest,
    HealthResponse,
    InterruptRequest,
    ProviderResponse,
    SessionResponse,
)

router = APIRouter()


@router.get("/internal/health", response_model=HealthResponse, include_in_schema=False)
@router.get("/api/health", response_model=HealthResponse, include_in_schema=False)
@router.get("/health", response_model=HealthResponse, include_in_schema=False)
async def health(request: Request) -> HealthResponse:
    container = get_container(request)
    return HealthResponse(service=container.settings.service_name, version="0.1.7")


@router.get("/internal/providers", response_model=list[ProviderResponse])
async def providers(context: InternalContext, request: Request) -> list[ProviderResponse]:
    del context
    container = get_container(request)
    health_items = await container.provider_service.list()
    result: list[ProviderResponse] = []
    for item in health_items:
        capabilities = await container.providers.capabilities(item.provider)
        result.append(
            ProviderResponse(
                provider=item.provider,
                status=item.status,
                configured=item.configured,
                detail=item.detail,
                capabilities=capabilities.model_dump(mode="json"),
            )
        )
    return result


@router.get("/internal/configuration")
async def configuration(context: InternalContext, request: Request) -> dict[str, Any]:
    del context
    return await get_container(request).configuration_service.view()


@router.patch("/internal/configuration")
async def update_configuration(
    payload: ConfigurationPatch,
    context: InternalContext,
    request: Request,
) -> dict[str, Any]:
    if context.get("user_role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅管理员可修改运行配置")
    try:
        return await get_container(request).configuration_service.update(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/internal/sessions", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: CreateSessionRequest,
    context: InternalContext,
    request: Request,
) -> SessionResponse:
    container = get_container(request)
    provider = payload.provider or container.settings.default_provider
    try:
        session = await container.session_service.create(user_id=context["user_id"], provider_name=provider)
    except ApplicationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return _session_response(session)


@router.delete("/internal/sessions/{session_id}", response_model=SessionResponse | None)
async def close_session(session_id: str, context: InternalContext, request: Request):
    container = get_container(request)
    try:
        session = await container.session_service.close(user_id=context["user_id"], session_id=session_id)
    except ApplicationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return _session_response(session) if session else None


@router.post("/internal/sessions/{session_id}/interrupt", response_model=SessionResponse)
async def interrupt_session(
    session_id: str,
    context: InternalContext,
    request: Request,
    payload: InterruptRequest | None = None,
) -> SessionResponse:
    container = get_container(request)
    try:
        session = await container.session_service.interrupt(
            user_id=context["user_id"],
            session_id=session_id,
            run_id=payload.run_id if payload else None,
        )
    except ApplicationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return _session_response(session)


@router.post("/internal/sessions/{session_id}/close", response_model=SessionResponse | None)
async def close_session_action(session_id: str, context: InternalContext, request: Request):
    """Action-style close alias for clients that cannot issue DELETE."""
    return await close_session(session_id, context, request)


@router.post("/internal/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, context: InternalContext, request: Request) -> ChatResponse:
    container = get_container(request)
    try:
        result = await container.chat_service.send(
            user_id=context["user_id"],
            user_name=context["user_name"],
            session_id=payload.session_id,
            message=payload.message,
        )
    except ApplicationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return _chat_response(result)


@router.post("/internal/chat/stream")
async def chat_stream(payload: ChatRequest, context: InternalContext, request: Request) -> StreamingResponse:
    container = get_container(request)
    try:
        events = await container.chat_service.stream(
            user_id=context["user_id"],
            user_name=context["user_name"],
            session_id=payload.session_id,
            message=payload.message,
        )
    except ApplicationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return StreamingResponse(
        iter_sse_frames(events, request, session_id=payload.session_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


def _session_response(session: AvatarSession | None) -> SessionResponse | None:
    if session is None:
        return None
    return SessionResponse(
        sessionId=session.session_id,
        provider=session.provider,
        userId=session.user_id,
        capabilities=session.capabilities.model_dump(mode="json"),
        createdAt=session.created_at,
        expiresAt=session.expires_at,
        status=session.status,
        clientParams=browser_safe_client_params(session.client_params),
    )


def _chat_response(result: ChatResult) -> ChatResponse:
    return ChatResponse(
        reply=result.reply,
        traceId=result.trace_id,
        sessionId=result.session_id,
        runId=result.run_id,
        provider=result.provider,
        toolCalls=[call.model_dump(mode="json") for call in result.tool_calls],
        agent_latency_ms=result.agent_latency_ms,
        digital_human_latency_ms=result.digital_human_latency_ms,
        first_event_latency_ms=result.first_event_latency_ms,
        first_visible_latency_ms=result.first_visible_latency_ms,
        cancellation_latency_ms=result.cancellation_latency_ms,
        interrupted=result.interrupted,
        agent_response=result.agent_response,
    )
