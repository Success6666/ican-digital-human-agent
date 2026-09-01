"""Environment-backed service settings.

Keeping configuration in one small module makes it possible to replace the
in-memory runtime with Redis or a different MCP endpoint without touching the
domain and graph layers.
"""

from __future__ import annotations

from functools import lru_cache
import math
import os

from pydantic import BaseModel, Field, field_validator, model_validator

from .mcp.limits import (
    DEFAULT_MAX_RESULT_BYTES,
    DEFAULT_MAX_RESULT_DEPTH,
    DEFAULT_MAX_RESULT_ITEMS,
    MIN_MAX_RESULT_BYTES,
)
from .rag.limits import (
    DEFAULT_MAX_METADATA_BYTES,
    DEFAULT_MAX_METADATA_DEPTH,
    DEFAULT_MAX_METADATA_ITEMS,
)

_DEFAULT_INTERNAL_TOKEN = "dev-internal-token"
_PRODUCTION_TOKEN_MIN_LENGTH = 32
_PRODUCTION_TOKEN_PLACEHOLDERS = frozenset(
    {
        _DEFAULT_INTERNAL_TOKEN,
        "replace-with-a-long-random-token",
        "replace-with-a-different-long-random-token",
    }
)


class Settings(BaseModel):
    service_name: str = "agent-service"
    environment: str = "development"
    host: str = Field(default="0.0.0.0", alias="AGENT_HOST")
    port: int = Field(default=8000, alias="AGENT_PORT")
    internal_token: str = Field(default="dev-internal-token", alias="AGENT_INTERNAL_TOKEN")
    mcp_server_url: str = Field(default="http://localhost:9000/mcp", alias="MCP_SERVER_URL")
    rabbitmq_url: str = Field(default="", alias="RABBITMQ_URL")
    rabbitmq_exchange: str = Field(default="ican.agent", alias="RABBITMQ_EXCHANGE")
    rabbitmq_queue: str = Field(default="digital-human.presentation.v2", alias="RABBITMQ_QUEUE")
    rabbitmq_publish_timeout_seconds: float = Field(default=2.0, alias="RABBITMQ_PUBLISH_TIMEOUT_SECONDS", gt=0, le=5)
    rabbitmq_max_in_flight: int = Field(default=512, alias="RABBITMQ_MAX_IN_FLIGHT", ge=1, le=10_000)
    rabbitmq_prefetch_count: int = Field(default=256, alias="RABBITMQ_PREFETCH_COUNT", ge=1, le=10_000)
    rabbitmq_retry_limit: int = Field(default=3, alias="RABBITMQ_RETRY_LIMIT", ge=0, le=20)
    session_store_backend: str = Field(default="memory", alias="SESSION_STORE_BACKEND", min_length=1, max_length=16)
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL", min_length=1, max_length=512)
    redis_key_prefix: str = Field(default="ican:agent", alias="REDIS_KEY_PREFIX", min_length=1, max_length=128)
    redis_operation_timeout_seconds: float = Field(default=0.25, alias="REDIS_OPERATION_TIMEOUT_SECONDS", gt=0, le=10)
    response_cache_enabled: bool = Field(default=True, alias="RESPONSE_CACHE_ENABLED")
    response_cache_ttl_seconds: int = Field(default=300, alias="RESPONSE_CACHE_TTL_SECONDS", ge=5, le=86_400)
    response_cache_max_bytes: int = Field(default=256_000, alias="RESPONSE_CACHE_MAX_BYTES", ge=1024, le=8 * 1024 * 1024)
    response_cache_max_entries: int = Field(default=100_000, alias="RESPONSE_CACHE_MAX_ENTRIES", ge=100, le=1_000_000)
    response_cache_scope: str = Field(default="tenant", alias="RESPONSE_CACHE_SCOPE", pattern="^(tenant|user)$")
    response_cache_lock_seconds: int = Field(default=15, alias="RESPONSE_CACHE_LOCK_SECONDS", ge=2, le=300)
    agent_max_in_flight_requests: int = Field(default=4096, alias="AGENT_MAX_IN_FLIGHT_REQUESTS", ge=1, le=20_000)
    mcp_internal_token: str = Field(default="", alias="MCP_INTERNAL_TOKEN")
    mcp_allow_local_fallback: bool = Field(default=True, alias="MCP_ALLOW_LOCAL_FALLBACK")
    default_provider: str = Field(default="mock", alias="DEFAULT_PROVIDER")
    runtime_configuration_file: str = Field(
        default="data/runtime-configuration.json",
        alias="RUNTIME_CONFIGURATION_FILE",
    )
    session_ttl_seconds: int = Field(default=1800, alias="SESSION_TTL_SECONDS", ge=1, le=86_400)
    cleanup_interval_seconds: int = Field(default=30, alias="SESSION_CLEANUP_INTERVAL_SECONDS", ge=1, le=3_600)
    session_max_sessions: int = Field(default=1024, alias="SESSION_MAX_SESSIONS", ge=1, le=100_000)
    session_cleanup_batch_size: int = Field(default=100, alias="SESSION_CLEANUP_BATCH_SIZE", ge=1, le=10_000)
    session_cleanup_outbox_path: str = Field(
        default="data/session-cleanup-outbox.jsonl",
        alias="SESSION_CLEANUP_OUTBOX_PATH",
        min_length=1,
        max_length=512,
    )
    session_idle_timeout_seconds: int = Field(default=1800, alias="SESSION_IDLE_TIMEOUT_SECONDS", ge=1, le=86_400)
    session_heartbeat_interval_seconds: int = Field(
        default=15,
        alias="SESSION_HEARTBEAT_INTERVAL_SECONDS",
        ge=1,
        le=3_600,
    )
    realtime_handshake_timeout_seconds: float = Field(
        default=5.0,
        alias="REALTIME_HANDSHAKE_TIMEOUT_SECONDS",
        gt=0,
        le=60,
    )
    realtime_idle_timeout_seconds: float = Field(
        default=45.0,
        alias="REALTIME_IDLE_TIMEOUT_SECONDS",
        gt=0,
        le=86_400,
    )
    realtime_interrupt_timeout_seconds: float = Field(
        default=0.25,
        alias="REALTIME_INTERRUPT_TIMEOUT_SECONDS",
        gt=0,
        le=10,
    )
    asr_endpoint: str = Field(default="", alias="HTTP_ASR_ENDPOINT", max_length=512)
    asr_api_key: str = Field(default="", alias="HTTP_ASR_API_KEY", max_length=512)
    asr_timeout_seconds: float = Field(default=8.0, alias="HTTP_ASR_TIMEOUT_SECONDS", gt=0, le=60)
    asr_max_response_bytes: int = Field(default=1_048_576, alias="HTTP_ASR_MAX_RESPONSE_BYTES", ge=1024, le=16 * 1024 * 1024)
    tts_endpoint: str = Field(default="", alias="HTTP_TTS_ENDPOINT", max_length=512)
    tts_api_key: str = Field(default="", alias="HTTP_TTS_API_KEY", max_length=512)
    tts_timeout_seconds: float = Field(default=8.0, alias="HTTP_TTS_TIMEOUT_SECONDS", gt=0, le=60)
    tts_chunk_bytes: int = Field(default=640, alias="HTTP_TTS_CHUNK_BYTES", ge=320, le=64 * 1024)
    tts_max_response_bytes: int = Field(default=4 * 1024 * 1024, alias="HTTP_TTS_MAX_RESPONSE_BYTES", ge=1024, le=32 * 1024 * 1024)
    max_message_length: int = Field(default=4000, alias="MAX_MESSAGE_LENGTH")
    max_request_body_bytes: int = Field(default=16 * 1024 * 1024, alias="AGENT_MAX_REQUEST_BODY_BYTES")
    request_timeout_seconds: float = Field(default=8.0, alias="MCP_REQUEST_TIMEOUT_SECONDS")
    mcp_fast_path_timeout_seconds: float = Field(default=0.25, alias="MCP_FAST_PATH_TIMEOUT_SECONDS")
    provider_cancel_grace_seconds: float = Field(default=0.25, alias="PROVIDER_CANCEL_GRACE_SECONDS")
    mcp_max_result_bytes: int = Field(default=DEFAULT_MAX_RESULT_BYTES, alias="MCP_MAX_RESULT_BYTES")
    mcp_max_result_items: int = Field(default=DEFAULT_MAX_RESULT_ITEMS, alias="MCP_MAX_RESULT_ITEMS")
    mcp_max_result_depth: int = Field(default=DEFAULT_MAX_RESULT_DEPTH, alias="MCP_MAX_RESULT_DEPTH")
    mcp_max_parallel_tools: int = Field(default=4, alias="MCP_MAX_PARALLEL_TOOLS", ge=1, le=32)
    rag_max_document_bytes: int = Field(default=8 * 1024 * 1024, alias="RAG_MAX_DOCUMENT_BYTES")
    rag_max_metadata_bytes: int = Field(default=DEFAULT_MAX_METADATA_BYTES, alias="RAG_MAX_METADATA_BYTES")
    rag_max_metadata_items: int = Field(default=DEFAULT_MAX_METADATA_ITEMS, alias="RAG_MAX_METADATA_ITEMS")
    rag_max_metadata_depth: int = Field(default=DEFAULT_MAX_METADATA_DEPTH, alias="RAG_MAX_METADATA_DEPTH")
    rag_parse_concurrency: int = Field(default=1, alias="RAG_PARSE_CONCURRENCY", ge=1, le=8)
    rag_store_path: str = Field(default="data/rag.sqlite3", alias="RAG_STORE_PATH", min_length=1, max_length=512)
    docling_max_concurrency: int = Field(default=1, alias="DOCLING_MAX_CONCURRENCY", ge=1, le=8)
    evaluation_buffer_size: int = Field(default=2000, alias="EVALUATION_BUFFER_SIZE")
    evaluation_raw_archive_path: str = Field(default="data/evaluation-runs.raw.jsonl", alias="EVALUATION_RAW_ARCHIVE_PATH", min_length=1, max_length=512)
    eval_input_price_per_1k: float = Field(default=0.003, alias="EVAL_INPUT_PRICE_PER_1K")
    eval_output_price_per_1k: float = Field(default=0.009, alias="EVAL_OUTPUT_PRICE_PER_1K")
    eval_currency: str = Field(default="CNY", alias="EVAL_CURRENCY")
    observability_max_pending_tasks: int = Field(
        default=256,
        alias="OBSERVABILITY_MAX_PENDING_TASKS",
        ge=1,
        le=4096,
    )
    observability_pending_flush_timeout_seconds: float = Field(
        default=2.0,
        alias="OBSERVABILITY_PENDING_FLUSH_TIMEOUT_SECONDS",
        gt=0,
        le=60,
    )
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8088",
            "http://127.0.0.1:8088",
        ]
    )
    provider_enabled: dict[str, bool] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}

    @field_validator(
        "session_ttl_seconds",
        "cleanup_interval_seconds",
        "session_max_sessions",
        "session_cleanup_batch_size",
        "session_idle_timeout_seconds",
        "session_heartbeat_interval_seconds",
        "max_message_length",
        "max_request_body_bytes",
        "mcp_max_result_bytes",
        "mcp_max_result_items",
        "mcp_max_result_depth",
        "mcp_max_parallel_tools",
        "rag_max_document_bytes",
        "rag_max_metadata_bytes",
        "rag_max_metadata_items",
        "rag_max_metadata_depth",
        "rag_parse_concurrency",
        "docling_max_concurrency",
        "evaluation_buffer_size",
        "observability_max_pending_tasks",
    )
    @classmethod
    def positive_int(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("must be positive")
        return value

    @model_validator(mode="after")
    def validate_session_lease_window(self) -> "Settings":
        if self.session_idle_timeout_seconds <= self.session_heartbeat_interval_seconds:
            raise ValueError(
                "session_idle_timeout_seconds must exceed session_heartbeat_interval_seconds"
            )
        if self.realtime_idle_timeout_seconds <= self.session_heartbeat_interval_seconds:
            raise ValueError(
                "realtime_idle_timeout_seconds must exceed session_heartbeat_interval_seconds"
            )
        if self.realtime_idle_timeout_seconds > self.session_idle_timeout_seconds:
            raise ValueError(
                "realtime_idle_timeout_seconds must not exceed session_idle_timeout_seconds"
            )
        if self.environment.strip().casefold() in {"prod", "production"}:
            if _unsafe_production_token(self.internal_token):
                raise ValueError("AGENT_INTERNAL_TOKEN must be replaced in production")
            if _unsafe_production_token(self.mcp_internal_token):
                raise ValueError("MCP_INTERNAL_TOKEN must be replaced in production")
        return self

    @field_validator("mcp_max_result_bytes")
    @classmethod
    def result_bytes_minimum(cls, value: int) -> int:
        if value < MIN_MAX_RESULT_BYTES:
            raise ValueError(f"must be at least {MIN_MAX_RESULT_BYTES} bytes")
        return value

    @field_validator(
        "request_timeout_seconds",
        "mcp_fast_path_timeout_seconds",
        "provider_cancel_grace_seconds",
        "realtime_handshake_timeout_seconds",
        "realtime_idle_timeout_seconds",
        "realtime_interrupt_timeout_seconds",
        "observability_pending_flush_timeout_seconds",
    )
    @classmethod
    def positive_timeout(cls, value: float) -> float:
        if not math.isfinite(value) or value <= 0:
            raise ValueError("must be positive")
        return value

    @field_validator("eval_input_price_per_1k", "eval_output_price_per_1k")
    @classmethod
    def nonnegative_price(cls, value: float) -> float:
        if not math.isfinite(value) or value < 0:
            raise ValueError("must be non-negative")
        return value

    @classmethod
    def from_env(cls) -> "Settings":
        values: dict[str, object] = {}
        for field_name, field in cls.model_fields.items():
            env_name = field.alias or field_name.upper()
            raw = os.getenv(env_name)
            if raw is None and field_name == "request_timeout_seconds":
                raw = os.getenv("REQUEST_TIMEOUT_SECONDS")
            if raw is not None:
                values[field_name] = raw

        # The MCP container can use the same secret as the Agent when a
        # dedicated MCP_INTERNAL_TOKEN is not supplied.
        if not values.get("mcp_internal_token"):
            values["mcp_internal_token"] = os.getenv("AGENT_INTERNAL_TOKEN", _DEFAULT_INTERNAL_TOKEN)

        values["cors_origins"] = _csv(
            os.getenv(
                "CORS_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8088,http://127.0.0.1:8088",
            )
        )
        values["provider_enabled"] = {
            name: _truthy_any(
                os.getenv(f"PROVIDER_{name.upper()}_ENABLED"),
                os.getenv(_provider_flag(name), "false"),
            )
            for name in ("aliyun", "mofa", "iflytek", "fay")
        }
        return cls.model_validate(values)


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _unsafe_production_token(value: str) -> bool:
    normalized = value.strip().casefold() if value else ""
    return (
        not normalized
        or normalized in _PRODUCTION_TOKEN_PLACEHOLDERS
        or len(value.strip()) < _PRODUCTION_TOKEN_MIN_LENGTH
    )


def _truthy_any(primary: str | None, fallback: str) -> bool:
    return _truthy(primary) if primary is not None else _truthy(fallback)


def _provider_flag(name: str) -> str:
    return {
        "aliyun": "ALIYUN_AVATAR_ENABLED",
        "mofa": "MOFA_AVATAR_ENABLED",
        "iflytek": "IFLYTEK_AVATAR_ENABLED",
        "fay": "FAY_ENABLED",
    }[name]


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
