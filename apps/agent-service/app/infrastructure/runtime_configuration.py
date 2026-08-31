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


class RuntimeConfiguration(BaseModel):
    """The small set of settings that can be changed without secrets."""

    model_config = ConfigDict(extra="forbid")

    default_provider: str = Field(default="mock", min_length=1, max_length=64)
    session_ttl_seconds: int = Field(default=1800, ge=60, le=86_400)
    cleanup_interval_seconds: int = Field(default=30, ge=5, le=3_600)
    mofa: "MofaRuntimeConfiguration" = Field(default_factory=lambda: MofaRuntimeConfiguration())
    aliyun: "AliyunRuntimeConfiguration" = Field(default_factory=lambda: AliyunRuntimeConfiguration())
    iflytek: "IflytekRuntimeConfiguration" = Field(default_factory=lambda: IflytekRuntimeConfiguration())

    @classmethod
    def from_settings(cls, settings: Any) -> "RuntimeConfiguration":
        return cls(
            default_provider=settings.default_provider,
            session_ttl_seconds=settings.session_ttl_seconds,
            cleanup_interval_seconds=settings.cleanup_interval_seconds,
            mofa=MofaRuntimeConfiguration.from_env(),
            aliyun=AliyunRuntimeConfiguration.from_env(),
            iflytek=IflytekRuntimeConfiguration.from_env(),
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
]
