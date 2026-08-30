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
    os.environ["MOFA_AVATAR_ENABLED"] = "true" if configuration.enabled else "false"
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


class RuntimeConfiguration(BaseModel):
    """The small set of settings that can be changed without secrets."""

    model_config = ConfigDict(extra="forbid")

    default_provider: str = Field(default="mock", min_length=1, max_length=64)
    session_ttl_seconds: int = Field(default=1800, ge=60, le=86_400)
    cleanup_interval_seconds: int = Field(default=30, ge=5, le=3_600)
    mofa: "MofaRuntimeConfiguration" = Field(default_factory=lambda: MofaRuntimeConfiguration())

    @classmethod
    def from_settings(cls, settings: Any) -> "RuntimeConfiguration":
        return cls(
            default_provider=settings.default_provider,
            session_ttl_seconds=settings.session_ttl_seconds,
            cleanup_interval_seconds=settings.cleanup_interval_seconds,
            mofa=MofaRuntimeConfiguration.from_env(),
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


__all__ = ["MofaRuntimeConfiguration", "RuntimeConfiguration", "RuntimeConfigurationRepository", "apply_mofa_environment"]
