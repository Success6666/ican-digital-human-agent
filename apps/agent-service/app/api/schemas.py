"""HTTP request/response DTOs with camelCase wire aliases."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..domain.models import AgentResponse, SessionStatus


class ProviderResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    provider: str
    default: bool = False
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


class ChatHistoryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    session_id: str = Field(alias="sessionId", min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=4000)
    history: list[ChatHistoryMessage] = Field(default_factory=list, max_length=12)


class ProfilePatch(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    language: str | None = Field(default=None, max_length=64)
    tone: str | None = Field(default=None, max_length=128)
    voice: str | None = Field(default=None, max_length=128)
    verbosity: str | None = Field(default=None, max_length=32)
    constraints: str | None = Field(default=None, max_length=512)


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
    cache_hit: bool = Field(default=False, alias="cacheHit")
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


class AliyunConfigurationPatch(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    enabled: bool | None = None
    base_url: str | None = Field(default=None, alias="baseUrl", max_length=512)
    app_id: str | None = Field(default=None, alias="appId", max_length=128)
    instance_id: str | None = Field(default=None, alias="instanceId", max_length=128)
    access_key_id: str | None = Field(default=None, alias="accessKeyId", max_length=256)
    access_key_secret: str | None = Field(default=None, alias="accessKeySecret", max_length=256)


class IflytekConfigurationPatch(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    enabled: bool | None = None
    gateway_url: str | None = Field(default=None, alias="gatewayUrl", max_length=512)
    app_id: str | None = Field(default=None, alias="appId", max_length=128)
    api_key: str | None = Field(default=None, alias="apiKey", max_length=256)
    api_secret: str | None = Field(default=None, alias="apiSecret", max_length=256)


class LlmConfigurationPatch(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    enabled: bool | None = None
    provider: str | None = Field(default=None, max_length=64)
    base_url: str | None = Field(default=None, alias="baseUrl", max_length=512)
    api_key: str | None = Field(default=None, alias="apiKey", max_length=512)
    model: str | None = Field(default=None, max_length=128)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, alias="maxTokens", ge=64, le=16_384)


class EmbeddingConfigurationPatch(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    enabled: bool | None = None
    provider: str | None = Field(default=None, max_length=64)
    base_url: str | None = Field(default=None, alias="baseUrl", max_length=512)
    api_key: str | None = Field(default=None, alias="apiKey", max_length=512)
    model: str | None = Field(default=None, max_length=128)
    dimensions: int | None = Field(default=None, ge=16, le=4096)


class DoclingConfigurationPatch(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    enabled: bool | None = None
    artifacts_path: str | None = Field(default=None, alias="artifactsPath", max_length=512)
    ocr_backend: str | None = Field(default=None, alias="ocrBackend", max_length=64)
    ocr_languages: list[str] | None = Field(default=None, alias="ocrLanguages", min_length=1, max_length=16)
    do_ocr: bool | None = Field(default=None, alias="doOcr")
    do_table_structure: bool | None = Field(default=None, alias="doTableStructure")
    table_mode: str | None = Field(default=None, alias="tableMode", pattern="^(fast|accurate)$")
    max_concurrency: int | None = Field(default=None, alias="maxConcurrency", ge=1, le=8)


class FutureAGIConfigurationPatch(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    enabled: bool | None = None
    endpoint: str | None = Field(default=None, max_length=512)
    api_key: str | None = Field(default=None, alias="apiKey", max_length=512)
    secret_key: str | None = Field(default=None, alias="secretKey", max_length=512)
    project: str | None = Field(default=None, max_length=128)


class ConfigurationPatch(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    default_provider: str | None = Field(default=None, alias="defaultProvider", min_length=1, max_length=64)
    session: SessionConfigurationPatch | None = None
    mofa: MofaConfigurationPatch | None = None
    aliyun: AliyunConfigurationPatch | None = None
    iflytek: IflytekConfigurationPatch | None = None
    llm: LlmConfigurationPatch | None = None
    embedding: EmbeddingConfigurationPatch | None = None
    docling: DoclingConfigurationPatch | None = None
    futureagi: FutureAGIConfigurationPatch | None = None

    @model_validator(mode="after")
    def require_change(self) -> "ConfigurationPatch":
        if self.default_provider is None and self.session is None and self.mofa is None and self.aliyun is None and self.iflytek is None and self.llm is None and self.embedding is None and self.docling is None and self.futureagi is None:
            raise ValueError("至少需要提交一项配置")
        if self.session is not None and self.session.ttl_seconds is None and self.session.cleanup_interval_seconds is None:
            raise ValueError("会话配置不能为空")
        if self.mofa is not None and all(value is None for value in self.mofa.model_dump().values()):
            raise ValueError("星云配置不能为空")
        if self.aliyun is not None and all(value is None for value in self.aliyun.model_dump().values()):
            raise ValueError("阿里云配置不能为空")
        if self.iflytek is not None and all(value is None for value in self.iflytek.model_dump().values()):
            raise ValueError("讯飞配置不能为空")
        for name, value in (("LLM", self.llm), ("Embedding", self.embedding), ("Docling", self.docling), ("FutureAGI", self.futureagi)):
            if value is not None and all(item is None for item in value.model_dump().values()):
                raise ValueError(f"{name} 配置不能为空")
        return self
