"""HTTP request/response DTOs with camelCase wire aliases."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    first_event_latency_ms: float | None = Field(default=None, alias="firstEventLatencyMs")
    first_visible_latency_ms: float | None = Field(default=None, alias="firstVisibleLatencyMs")
    cancellation_latency_ms: float | None = Field(default=None, alias="cancellationLatencyMs")
    interrupted: bool = False
    agent_response: AgentResponse | None = Field(default=None, alias="agentResponse")


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str
    version: str


class SessionConfigurationPatch(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    ttl_seconds: int | None = Field(default=None, alias="ttlSeconds", ge=60, le=86_400)
    cleanup_interval_seconds: int | None = Field(
        default=None, alias="cleanupIntervalSeconds", ge=5, le=3_600
    )


class MofaConfigurationPatch(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    enabled: bool | None = None
    app_id: str | None = Field(default=None, alias="appId", max_length=128)
    app_secret: str | None = Field(default=None, alias="appSecret", max_length=256)
    authorization: str | None = Field(default=None, max_length=256)
    gateway_url: str | None = Field(default=None, alias="gatewayUrl", max_length=512)
    sdk_url: str | None = Field(default=None, alias="sdkUrl", max_length=512)
    crypto_url: str | None = Field(default=None, alias="cryptoUrl", max_length=512)


class ConfigurationPatch(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    default_provider: str | None = Field(default=None, alias="defaultProvider", min_length=1, max_length=64)
    session: SessionConfigurationPatch | None = None
    mofa: MofaConfigurationPatch | None = None

    @model_validator(mode="after")
    def require_change(self) -> "ConfigurationPatch":
        if self.default_provider is None and self.session is None and self.mofa is None:
            raise ValueError("至少需要提交一项配置")
        if self.session is not None and self.session.ttl_seconds is None and self.session.cleanup_interval_seconds is None:
            raise ValueError("会话配置不能为空")
        if self.mofa is not None and all(value is None for value in self.mofa.model_dump().values()):
            raise ValueError("星云配置不能为空")
        return self
