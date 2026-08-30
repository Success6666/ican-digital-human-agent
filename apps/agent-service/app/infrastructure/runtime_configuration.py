"""Persisted, non-sensitive runtime configuration overrides."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RuntimeConfiguration(BaseModel):
    """The small set of settings that can be changed without secrets."""

    model_config = ConfigDict(extra="forbid")

    default_provider: str = Field(default="mock", min_length=1, max_length=64)
    session_ttl_seconds: int = Field(default=1800, ge=60, le=86_400)
    cleanup_interval_seconds: int = Field(default=30, ge=5, le=3_600)

    @classmethod
    def from_settings(cls, settings: Any) -> "RuntimeConfiguration":
        return cls(
            default_provider=settings.default_provider,
            session_ttl_seconds=settings.session_ttl_seconds,
            cleanup_interval_seconds=settings.cleanup_interval_seconds,
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


__all__ = ["RuntimeConfiguration", "RuntimeConfigurationRepository"]
