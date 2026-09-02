"""Persisted, non-sensitive runtime configuration overrides."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def apply_mofa_environment(configuration: "MofaRuntimeConfiguration") -> None:
    """Apply persisted provider settings to the current process environment."""
    for key, value in {
        "MOFA_APP_ID": configuration.app_id,
        "MOFA_APP_SECRET": configuration.app_secret,
        "MOFA_AUTHORIZATION": configuration.authorization,
        "MOFA_GATEWAY_URL": configuration.gateway_url,
        "MOFA_SDK_URL": configuration.sdk_url,
        "MOFA_CRYPTO_URL": configuration.crypto_url,
    }.items():
        if value:
            os.environ[key] = value
        else:
            os.environ.pop(key, None)


def _apply_environment(values: dict[str, str]) -> None:
    for key, value in values.items():
        if value:
            os.environ[key] = value
        else:
            os.environ.pop(key, None)


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


class MofaRuntimeConfiguration(BaseModel):
    """Server-owned Xingyun settings; secrets are never returned by the API."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    app_id: str = Field(default="", max_length=128)
    app_secret: str = Field(default="", max_length=256)
    authorization: str = Field(default="", max_length=256)
    gateway_url: str = Field(default="", max_length=512)
    sdk_url: str = Field(default="", max_length=512)
    crypto_url: str = Field(default="", max_length=512)

    @classmethod
    def from_env(cls) -> "MofaRuntimeConfiguration":
        return cls(
            enabled=os.getenv("MOFA_AVATAR_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"},
            app_id=os.getenv("MOFA_APP_ID", "").strip(),
            app_secret=os.getenv("MOFA_APP_SECRET", "").strip(),
            authorization=os.getenv("MOFA_AUTHORIZATION", "").strip(),
            gateway_url=os.getenv("MOFA_GATEWAY_URL", "").strip(),
            sdk_url=os.getenv("MOFA_SDK_URL", "").strip(),
            crypto_url=os.getenv("MOFA_CRYPTO_URL", "").strip(),
        )


class AliyunRuntimeConfiguration(BaseModel):
    """Server-owned Alibaba Cloud avatar settings."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    base_url: str = Field(default="", max_length=512)
    app_id: str = Field(default="", max_length=128)
    instance_id: str = Field(default="", max_length=128)
    access_key_id: str = Field(default="", max_length=256)
    access_key_secret: str = Field(default="", max_length=256)

    @classmethod
    def from_env(cls) -> "AliyunRuntimeConfiguration":
        return cls(
            enabled=os.getenv("ALIYUN_AVATAR_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"},
            base_url=os.getenv("ALIYUN_AVATAR_BASE_URL", "").strip(),
            app_id=os.getenv("ALIYUN_AVATAR_APP_ID", "").strip(),
            instance_id=os.getenv("ALIYUN_AVATAR_INSTANCE_ID", "").strip(),
            access_key_id=os.getenv("ALIYUN_AVATAR_ACCESS_KEY_ID", "").strip(),
            access_key_secret=os.getenv("ALIYUN_AVATAR_ACCESS_KEY_SECRET", "").strip(),
        )


class IflytekRuntimeConfiguration(BaseModel):
    """Server-owned iFlytek avatar settings."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    gateway_url: str = Field(default="", max_length=512)
    app_id: str = Field(default="", max_length=128)
    api_key: str = Field(default="", max_length=256)
    api_secret: str = Field(default="", max_length=256)

    @classmethod
    def from_env(cls) -> "IflytekRuntimeConfiguration":
        return cls(
            enabled=os.getenv("IFLYTEK_AVATAR_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"},
            gateway_url=os.getenv("IFLYTEK_GATEWAY_URL", "").strip(),
            app_id=os.getenv("IFLYTEK_APP_ID", "").strip(),
            api_key=os.getenv("IFLYTEK_API_KEY", "").strip(),
            api_secret=os.getenv("IFLYTEK_API_SECRET", "").strip(),
        )


def apply_aliyun_environment(configuration: AliyunRuntimeConfiguration) -> None:
    _apply_environment(
        {
            "ALIYUN_AVATAR_BASE_URL": configuration.base_url,
            "ALIYUN_AVATAR_APP_ID": configuration.app_id,
            "ALIYUN_AVATAR_INSTANCE_ID": configuration.instance_id,
            "ALIYUN_AVATAR_ACCESS_KEY_ID": configuration.access_key_id,
            "ALIYUN_AVATAR_ACCESS_KEY_SECRET": configuration.access_key_secret,
        },
    )


def apply_iflytek_environment(configuration: IflytekRuntimeConfiguration) -> None:
    _apply_environment(
        {
            "IFLYTEK_GATEWAY_URL": configuration.gateway_url,
            "IFLYTEK_APP_ID": configuration.app_id,
            "IFLYTEK_API_KEY": configuration.api_key,
            "IFLYTEK_API_SECRET": configuration.api_secret,
        },
    )


class LlmRuntimeConfiguration(BaseModel):
    """OpenAI-compatible LLM settings kept on the server."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    provider: str = Field(default="openai-compatible", max_length=64)
    base_url: str = Field(default="", max_length=512)
    api_key: str = Field(default="", max_length=512)
    model: str = Field(default="", max_length=128)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, ge=64, le=16_384)

    @classmethod
    def from_env(cls) -> "LlmRuntimeConfiguration":
        return cls(
            enabled=_truthy(os.getenv("LLM_ENABLED", "false")),
            provider=os.getenv("LLM_PROVIDER", "openai-compatible").strip(),
            base_url=os.getenv("LLM_BASE_URL", "").strip(),
            api_key=os.getenv("LLM_API_KEY", "").strip(),
            model=os.getenv("LLM_MODEL", "").strip(),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.2")),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "1024")),
        )


class EmbeddingRuntimeConfiguration(BaseModel):
    """Embedding settings with a local Chinese model as the default."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    provider: str = Field(default="local", max_length=64)
    base_url: str = Field(default="", max_length=512)
    api_key: str = Field(default="", max_length=512)
    model: str = Field(default="BAAI/bge-small-zh-v1.5", max_length=128)
    dimensions: int = Field(default=512, ge=16, le=4096)
    device: str = Field(default="auto", max_length=16)
    cache_dir: str = Field(default="/app/model-cache/sentence-transformers", max_length=512)
    batch_size: int = Field(default=64, ge=1, le=256)

    @classmethod
    def from_env(cls) -> "EmbeddingRuntimeConfiguration":
        return cls(
            enabled=_truthy(os.getenv("EMBEDDING_ENABLED", "true")),
            provider=os.getenv("EMBEDDING_PROVIDER", "local").strip(),
            base_url=os.getenv("EMBEDDING_BASE_URL", "").strip(),
            api_key=os.getenv("EMBEDDING_API_KEY", "").strip(),
            model=os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5").strip(),
            dimensions=int(os.getenv("EMBEDDING_DIMENSIONS", "512")),
            device=os.getenv("EMBEDDING_DEVICE", "auto").strip(),
            cache_dir=os.getenv("EMBEDDING_CACHE_DIR", "/app/model-cache/sentence-transformers").strip(),
            batch_size=int(os.getenv("EMBEDDING_BATCH_SIZE", "64")),
        )


class FutureAGIRuntimeConfiguration(BaseModel):
    """FutureAGI export settings with masked secrets in the API view."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    endpoint: str = Field(default="", max_length=512)
    api_key: str = Field(default="", max_length=512)
    secret_key: str = Field(default="", max_length=512)
    project: str = Field(default="ican-digital-human", max_length=128)

    @classmethod
    def from_env(cls) -> "FutureAGIRuntimeConfiguration":
        return cls(
            enabled=_truthy(os.getenv("FUTUREAGI_ENABLED", "false")),
            endpoint=os.getenv("FUTUREAGI_ENDPOINT", "").strip(),
            api_key=os.getenv("FUTUREAGI_API_KEY", "").strip(),
            secret_key=os.getenv("FUTUREAGI_SECRET_KEY", "").strip(),
            project=os.getenv("FUTUREAGI_PROJECT", "ican-digital-human").strip(),
        )


class DoclingRuntimeConfiguration(BaseModel):
    """Persisted controls for the local Docling parser."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    artifacts_path: str = Field(default="", max_length=512)
    ocr_backend: str = Field(default="onnxruntime", max_length=64)
    ocr_languages: list[str] = Field(default_factory=lambda: ["chinese"], min_length=1, max_length=16)
    do_ocr: bool = True
    do_table_structure: bool = True
    table_mode: str = Field(default="accurate", pattern="^(fast|accurate)$")
    max_concurrency: int = Field(default=1, ge=1, le=8)

    @classmethod
    def from_env(cls) -> "DoclingRuntimeConfiguration":
        languages = [item.strip() for item in os.getenv("DOCLING_OCR_LANG", "chinese").split(",") if item.strip()]
        return cls(
            enabled=_truthy(os.getenv("DOCLING_ENABLED", "true")),
            artifacts_path=os.getenv("DOCLING_ARTIFACTS_PATH", "").strip(),
            ocr_backend=os.getenv("DOCLING_OCR_BACKEND", "onnxruntime").strip(),
            ocr_languages=languages or ["chinese"],
            do_ocr=_truthy(os.getenv("DOCLING_DO_OCR", "true")),
            do_table_structure=_truthy(os.getenv("DOCLING_DO_TABLE_STRUCTURE", "true")),
            table_mode=os.getenv("DOCLING_TABLE_MODE", "accurate").strip(),
            max_concurrency=int(os.getenv("DOCLING_MAX_CONCURRENCY", "1")),
        )


def apply_llm_environment(configuration: LlmRuntimeConfiguration) -> None:
    _apply_environment(
        {
            "LLM_PROVIDER": configuration.provider,
            "LLM_BASE_URL": configuration.base_url,
            "LLM_API_KEY": configuration.api_key,
            "LLM_MODEL": configuration.model,
            "LLM_TEMPERATURE": str(configuration.temperature),
            "LLM_MAX_TOKENS": str(configuration.max_tokens),
        },
    )


def apply_embedding_environment(configuration: EmbeddingRuntimeConfiguration) -> None:
    _apply_environment(
        {
            "EMBEDDING_ENABLED": "true" if configuration.enabled else "false",
            "EMBEDDING_PROVIDER": configuration.provider,
            "EMBEDDING_BASE_URL": configuration.base_url,
            "EMBEDDING_API_KEY": configuration.api_key,
            "EMBEDDING_MODEL": configuration.model,
            "EMBEDDING_DIMENSIONS": str(configuration.dimensions),
            "EMBEDDING_DEVICE": configuration.device,
            "EMBEDDING_CACHE_DIR": configuration.cache_dir,
            "EMBEDDING_BATCH_SIZE": str(configuration.batch_size),
        },
    )


def apply_futureagi_environment(configuration: FutureAGIRuntimeConfiguration) -> None:
    _apply_environment(
        {
            "FUTUREAGI_ENDPOINT": configuration.endpoint,
            "FUTUREAGI_API_KEY": configuration.api_key,
            "FUTUREAGI_SECRET_KEY": configuration.secret_key,
            "FUTUREAGI_PROJECT": configuration.project,
        },
    )


def apply_docling_environment(configuration: DoclingRuntimeConfiguration) -> None:
    _apply_environment(
        {
            "DOCLING_ARTIFACTS_PATH": configuration.artifacts_path,
            "DOCLING_OCR_BACKEND": configuration.ocr_backend,
            "DOCLING_OCR_LANG": ",".join(configuration.ocr_languages),
            "DOCLING_TABLE_MODE": configuration.table_mode,
            "DOCLING_MAX_CONCURRENCY": str(configuration.max_concurrency),
        },
    )
    os.environ["DOCLING_ENABLED"] = "true" if configuration.enabled else "false"
    os.environ["DOCLING_DO_OCR"] = "true" if configuration.do_ocr else "false"
    os.environ["DOCLING_DO_TABLE_STRUCTURE"] = "true" if configuration.do_table_structure else "false"


class RuntimeConfiguration(BaseModel):
    """The small set of settings that can be changed without secrets."""

    model_config = ConfigDict(extra="forbid")

    default_provider: str = Field(default="mock", min_length=1, max_length=64)
    session_ttl_seconds: int = Field(default=1800, ge=60, le=86_400)
    cleanup_interval_seconds: int = Field(default=30, ge=5, le=3_600)
    mofa: "MofaRuntimeConfiguration" = Field(default_factory=lambda: MofaRuntimeConfiguration())
    aliyun: "AliyunRuntimeConfiguration" = Field(default_factory=lambda: AliyunRuntimeConfiguration())
    iflytek: "IflytekRuntimeConfiguration" = Field(default_factory=lambda: IflytekRuntimeConfiguration())
    llm: "LlmRuntimeConfiguration" = Field(default_factory=lambda: LlmRuntimeConfiguration())
    embedding: "EmbeddingRuntimeConfiguration" = Field(default_factory=lambda: EmbeddingRuntimeConfiguration())
    docling: "DoclingRuntimeConfiguration" = Field(default_factory=lambda: DoclingRuntimeConfiguration())
    futureagi: "FutureAGIRuntimeConfiguration" = Field(default_factory=lambda: FutureAGIRuntimeConfiguration())

    @classmethod
    def from_settings(cls, settings: Any) -> "RuntimeConfiguration":
        return cls(
            default_provider=settings.default_provider,
            session_ttl_seconds=settings.session_ttl_seconds,
            cleanup_interval_seconds=settings.cleanup_interval_seconds,
            mofa=MofaRuntimeConfiguration.from_env(),
            aliyun=AliyunRuntimeConfiguration.from_env(),
            iflytek=IflytekRuntimeConfiguration.from_env(),
            llm=LlmRuntimeConfiguration.from_env(),
            embedding=EmbeddingRuntimeConfiguration.from_env(),
            docling=DoclingRuntimeConfiguration.from_env(),
            futureagi=FutureAGIRuntimeConfiguration.from_env(),
        )


class RuntimeConfigurationRepository:
    """Atomically store safe overrides in a server-owned file."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def load(self, settings: Any) -> RuntimeConfiguration:
        current = RuntimeConfiguration.from_settings(settings)
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return current
            return RuntimeConfiguration.model_validate(
                {
                    **current.model_dump(),
                    **{key: payload[key] for key in type(current).model_fields if key in payload},
                }
            )
        except (OSError, ValueError, TypeError):
            return current

    def save(self, configuration: RuntimeConfiguration) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="runtime-configuration-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(configuration.model_dump(mode="json"), stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise


__all__ = [
    "AliyunRuntimeConfiguration",
    "IflytekRuntimeConfiguration",
    "MofaRuntimeConfiguration",
    "RuntimeConfiguration",
    "RuntimeConfigurationRepository",
    "apply_aliyun_environment",
    "apply_iflytek_environment",
    "apply_mofa_environment",
    "DoclingRuntimeConfiguration",
    "EmbeddingRuntimeConfiguration",
    "FutureAGIRuntimeConfiguration",
    "LlmRuntimeConfiguration",
    "apply_docling_environment",
    "apply_embedding_environment",
    "apply_futureagi_environment",
    "apply_llm_environment",
]
