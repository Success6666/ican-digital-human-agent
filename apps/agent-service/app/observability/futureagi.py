"""Optional FutureAGI/OpenTelemetry sink with local degradation."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from typing import Any

from .futureagi_runtime import FutureAGIRuntime, flush_runtime, register_runtime
from .local import LocalJsonLogSink
from .models import TelemetryEvent
from .redaction import redact, redact_text


@dataclass(frozen=True, slots=True)
class FutureAGIConfig:
    enabled: bool = False
    api_key: str | None = None
    secret_key: str | None = None
    project: str = "ican-digital-human"
    endpoint: str | None = None

    @classmethod
    def from_env(cls) -> "FutureAGIConfig":
        api_key = os.getenv("FUTUREAGI_API_KEY") or os.getenv("FI_API_KEY")
        secret_key = os.getenv("FUTUREAGI_SECRET_KEY") or os.getenv("FI_SECRET_KEY")
        enabled = _truthy(os.getenv("FUTUREAGI_ENABLED", "false")) or bool(api_key)
        return cls(
            enabled=enabled,
            api_key=api_key,
            secret_key=secret_key,
            project=os.getenv("FUTUREAGI_PROJECT", "ican-digital-human"),
            endpoint=os.getenv("FUTUREAGI_ENDPOINT") or os.getenv("FI_BASE_URL"),
        )


class FutureAGISink:
    """Bridge events to the optional ``fi_instrumentation`` OTel runtime.

    Registration is lazy so a normal local deployment has no optional import,
    network call, or credential requirement. Missing packages, bad credentials,
    and exporter errors are isolated and automatically use the bounded local
    JSON sink instead.
    """

    def __init__(
        self,
        config: FutureAGIConfig | None = None,
        *,
        fallback: LocalJsonLogSink | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config or FutureAGIConfig.from_env()
        # An explicitly supplied empty sink is still a valid caller-owned sink.
        self.fallback = fallback if fallback is not None else LocalJsonLogSink(logger=logger)
        self.logger = logger or logging.getLogger("ican.agent.observability.futureagi")
        self._runtime: FutureAGIRuntime | None = None
        self._error: str | None = None
        self._initialized = False

    @property
    def backend(self) -> str:
        return "futureagi" if self._runtime is not None else "local"

    @property
    def configured(self) -> bool:
        # fi-instrumentation-otel requires both headers for authenticated export.
        return bool(self.config.enabled and self.config.api_key and self.config.secret_key)

    @property
    def last_error(self) -> str | None:
        return self._error

    @property
    def local_sink(self) -> LocalJsonLogSink:
        return self.fallback

    async def emit(self, event: TelemetryEvent) -> None:
        self._ensure_initialized()
        if self._runtime is None:
            await self.fallback.emit(event)
            return
        try:
            self._emit_remote(event)
        except Exception as exc:
            self._degrade(exc)
            await self.fallback.emit(event)

    def emit_sync(self, event: TelemetryEvent) -> None:
        """Synchronous counterpart used by span start/end hooks."""
        self._ensure_initialized()
        if self._runtime is None:
            self.fallback.record_sync(event)
            return
        try:
            self._emit_remote(event)
        except Exception as exc:
            self._degrade(exc)
            self.fallback.record_sync(event)

    async def flush(self) -> None:
        try:
            await flush_runtime(self._runtime)
        except Exception as exc:
            self._degrade(exc)
        await self.fallback.flush()

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        if not self.configured:
            self._error = "FutureAGI credentials are not configured"
            return
        try:
            self._runtime = register_runtime(
                api_key=self.config.api_key or "",
                secret_key=self.config.secret_key or "",
                project=self.config.project,
                endpoint=self.config.endpoint,
            )
        except Exception as exc:
            self._degrade(exc)

    def _emit_remote(self, event: TelemetryEvent) -> None:
        runtime = self._runtime
        if runtime is None:
            return
        span = runtime.tracer.start_span(event.name)
        try:
            attributes = {
                "fi.event_type": event.event_type,
                "fi.trace_id": event.trace_id,
                "fi.span_id": event.span_id or "",
                "fi.parent_span_id": event.parent_span_id or "",
                "fi.status": event.status,
                **redact(event.attributes),
            }
            for key, value in attributes.items():
                try:
                    span.set_attribute(str(key), _otel_value(value))
                except Exception:
                    continue
            if event.error_message:
                try:
                    span.record_exception(Exception(event.error_message))
                except Exception:
                    pass
        finally:
            span.end()

    def _degrade(self, exc: Exception) -> None:
        self._runtime = None
        self._error = redact_text(f"{type(exc).__name__}: {exc}")
        self.logger.warning("FutureAGI telemetry degraded to local logging: %s", self._error)


def _otel_value(value: Any) -> str | int | float | bool:
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}
