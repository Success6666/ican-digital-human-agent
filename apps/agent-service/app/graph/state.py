"""Typed state exchanged by LangGraph nodes."""

from __future__ import annotations

from typing import Any, TypedDict

from ..domain.models import AgentResponse, ProviderResult, ToolCallRecord


class AgentGraphState(TypedDict, total=False):
    user_id: str
    user_name: str
    session_id: str
    message: str
    trace_id: str
    run_id: str
    intent: dict[str, Any]
    tool_plan: dict[str, Any]
    tool_calls: list[ToolCallRecord]
    rag_hits: list[dict[str, Any]]
    rag_error: str
    provider_result: ProviderResult
    agent_response: AgentResponse
    agent_latency_ms: float
    digital_human_latency_ms: float
    first_event_latency_ms: float
    first_visible_latency_ms: float
    cancellation_latency_ms: float
    provider_error: str
    llm_error: str
    reply: str
    presentation: dict[str, Any]
    error: str
    interrupted: bool
    security_blocked: bool
    security_reason: str
