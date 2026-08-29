"""Context-aware span lifecycle used by the observability facade."""

from __future__ import annotations

from contextvars import ContextVar, Token
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from .models import TelemetryEvent

if TYPE_CHECKING:
    from .service import ObservabilityService


_current_trace: ContextVar[str | None] = ContextVar("observability_trace", default=None)
_current_span: ContextVar[str | None] = ContextVar("observability_span", default=None)


class Span:
    """Synchronous and asynchronous context manager for one trace span."""

    def __init__(
        self,
        manager: "ObservabilityService",
        *,
        name: str,
        event_type: str,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        self.manager = manager
        self.name = name
        self.event_type = event_type
        self.trace_id = trace_id or _current_trace.get() or uuid4().hex
        self.span_id = uuid4().hex
        self.parent_span_id = parent_span_id if parent_span_id is not None else _current_span.get()
        self.attributes = dict(attributes or {})
        self.started_at: datetime | None = None
        self._token: Token[str | None] | None = None
        self._trace_token: Token[str | None] | None = None
        self._ended = False

    def __enter__(self) -> "Span":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc: Exception | None, tb: Any) -> None:
        self.end(error=exc)

    async def __aenter__(self) -> "Span":
        self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc: Exception | None, tb: Any) -> None:
        await self.aend(error=exc)

    def start(self) -> "Span":
        if self.started_at is not None:
            return self
        self.started_at = datetime.now(timezone.utc)
        self._token = _current_span.set(self.span_id)
        self._trace_token = _current_trace.set(self.trace_id)
        self.manager._emit_sync(self._event(event_type="span.start", status="unset", duration_ms=None))
        return self

    def set_attribute(self, key: str, value: Any) -> "Span":
        self.attributes[key] = value
        return self

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        self.manager.record_event(
            name,
            event_type="span.event",
            trace_id=self.trace_id,
            span_id=self.span_id,
            attributes=attributes,
        )

    def end(self, *, error: Exception | None = None, status: str | None = None) -> None:
        if self._ended:
            return
        self._ended = True
        if self.started_at is None:
            self.start()
        duration = (datetime.now(timezone.utc) - self.started_at).total_seconds() * 1000
        self.manager._emit_sync(
            self._event(
                event_type=self.event_type,
                status="error" if error else (status or "ok"),
                duration_ms=duration,
                error=error,
            )
        )
        self._reset_context()

    async def aend(self, *, error: Exception | None = None, status: str | None = None) -> None:
        if self._ended:
            return
        self._ended = True
        if self.started_at is None:
            self.start()
        duration = (datetime.now(timezone.utc) - self.started_at).total_seconds() * 1000
        await self.manager._emit_async(
            self._event(
                event_type=self.event_type,
                status="error" if error else (status or "ok"),
                duration_ms=duration,
                error=error,
            )
        )
        self._reset_context()

    def _event(
        self,
        *,
        event_type: str,
        status: str,
        duration_ms: float | None,
        error: Exception | None = None,
    ) -> TelemetryEvent:
        return TelemetryEvent(
            event_type=event_type,
            name=self.name,
            trace_id=self.trace_id,
            span_id=self.span_id,
            parent_span_id=self.parent_span_id,
            timestamp=self.started_at or datetime.now(timezone.utc),
            duration_ms=duration_ms,
            status=status,  # type: ignore[arg-type]
            attributes=self.attributes,
            error_type=type(error).__name__ if error else None,
            error_message=str(error)[:512] if error else None,
        )

    def _reset_context(self) -> None:
        if self._token is not None:
            try:
                _current_span.reset(self._token)
            except (RuntimeError, ValueError):
                pass
        if self._trace_token is not None:
            try:
                _current_trace.reset(self._trace_token)
            except (RuntimeError, ValueError):
                pass
