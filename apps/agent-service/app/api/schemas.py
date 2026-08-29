"""HTTP request/response DTOs with camelCase wire aliases."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..domain.models import AgentResponse, SessionStatus


class ProviderResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    provider: str
    status: str
    configured: bool
    detail: str | None = None
    capabilities: dict[str, Any] = Field(default_factory=dict)


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    provider: str | None = Field(default=None, min_length=1, max_length=64)


class SessionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    session_id: str = Field(alias="sessionId")
    provider: str
    user_id: str = Field(alias="userId")
    capabilities: dict[str, Any]
    created_at: datetime = Field(alias="createdAt")
    expires_at: datetime = Field(alias="expiresAt")
    status: SessionStatus
    client_params: dict[str, Any] = Field(default_factory=dict, alias="clientParams")


class ChatRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    session_id: str = Field(alias="sessionId", min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=4000)


class InterruptRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    run_id: str | None = Field(default=None, alias="runId", min_length=1, max_length=128)


class ChatResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    reply: str
    trace_id: str = Field(alias="traceId")
    session_id: str = Field(alias="sessionId")
    run_id: str | None = Field(default=None, alias="runId")
    provider: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list, alias="toolCalls")
    agent_latency_ms: float | None = Field(default=None, alias="agentLatencyMs")
    digital_human_latency_ms: float | None = Field(default=None, alias="digitalHumanLatencyMs")
    interrupted: bool = False
    agent_response: AgentResponse | None = Field(default=None, alias="agentResponse")


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str
    version: str
