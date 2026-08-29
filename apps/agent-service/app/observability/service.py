"""Context-aware trace/span facade for graph, MCP, RAG and providers."""

from __future__ import annotations

import asyncio
import inspect
import os
from typing import Any
from uuid import uuid4

from .futureagi import FutureAGIConfig, FutureAGISink
from .local import LocalJsonLogSink
from .models import ObservabilityHealth, TelemetryEvent, TraceReplay, TraceSummary
from .ports import EventSink
from .span import Span, _current_span, _current_trace
from .traces import replay as replay_trace
from .traces import summaries as summarize_traces

# Keep Span available from the original import path for downstream callers.
__all__ = [
    "ObservabilityService",
    "Span",
    "build_default_observability",
    "get_observability",
    "set_observability",
]


class ObservabilityService:
    """Emit provider-neutral telemetry and expose bounded diagnostic views."""

    def __init__(self, sink: EventSink, *, local_sink: LocalJsonLogSink | None = None) -> None:
        self.sink = sink
        self.local_sink = local_sink

    def start_trace(self, name: str = "agent.request", attributes: dict[str, Any] | None = None) -> Span:
        return Span(self, name=name, event_type="trace", attributes=attributes)

    def span(
        self,
        name: str,
        *,
        kind: str = "span",
        attributes: dict[str, Any] | None = None,
    ) -> Span:
        return Span(self, name=name, event_type=kind, attributes=attributes)

    def langgraph_node(self, name: str, *, attributes: dict[str, Any] | None = None) -> Span:
        return self.span(name, kind="langgraph.node", attributes=attributes)

    def mcp_call(self, name: str, *, attributes: dict[str, Any] | None = None) -> Span:
        return self.span(name, kind="mcp.call", attributes=attributes)

    def rag_retrieval(self, name: str = "rag.search", *, attributes: dict[str, Any] | None = None) -> Span:
        return self.span(name, kind="rag.retrieval", attributes=attributes)

    def provider_event(self, provider: str, name: str, *, attributes: dict[str, Any] | None = None) -> Span:
        values = {"provider": provider, **(attributes or {})}
        return self.span(name, kind="provider.event", attributes=values)

    def record_event(
        self,
        name: str,
        *,
        event_type: str = "event",
        attributes: dict[str, Any] | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
        error: Exception | None = None,
    ) -> None:
        self._emit_sync(
            self._make_event(
                name,
                event_type=event_type,
                attributes=attributes,
                trace_id=trace_id,
                span_id=span_id,
                error=error,
            )
        )

    async def arecord_event(self, *args: Any, **kwargs: Any) -> None:
        await self._emit_async(self._make_event(*args, **kwargs))

    def health(self) -> ObservabilityHealth:
        backend = getattr(self.sink, "backend", "unknown")
        configured = bool(getattr(self.sink, "configured", False))
        last_error = getattr(self.sink, "last_error", None)
        buffered = len(self.local_sink) if self.local_sink is not None else 0
        return ObservabilityHealth(
            status="degraded" if backend == "local" and not configured else "ok",
            backend=backend,
            configured=configured,
            buffered_events=buffered,
            last_error=last_error,
        )

    def recent(self, limit: int = 100, *, owner_id: str | None = None) -> list[TelemetryEvent]:
        if self.local_sink is None:
            return []
        events = self.local_sink.recent(1000 if owner_id is not None else limit)
        if owner_id is not None:
            events = [event for event in events if event.attributes.get("owner_id") == owner_id]
        return events[-max(0, min(limit, 500)) :] if limit > 0 else []

    def trace_summaries(self, *, limit: int = 30, owner_id: str | None = None) -> list[TraceSummary]:
        """Group buffered events into bounded, user-facing trace summaries."""
        return summarize_traces(self.recent(1000), limit=limit, owner_id=owner_id)

    def trace_replay(self, trace_id: str, *, owner_id: str | None = None) -> TraceReplay | None:
        """Return a sanitized, ordered event sequence for one trace."""
        return replay_trace(self.recent(1000), trace_id, owner_id=owner_id)

    async def flush(self) -> None:
        await self.sink.flush()

    def _make_event(
        self,
        name: str,
        *,
        event_type: str = "event",
        attributes: dict[str, Any] | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
        error: Exception | None = None,
    ) -> TelemetryEvent:
        return TelemetryEvent(
            event_type=event_type,
            name=name,
            trace_id=trace_id or _current_trace.get() or uuid4().hex,
            span_id=span_id or _current_span.get(),
            status="error" if error else "ok",
            attributes=attributes or {},
            error_type=type(error).__name__ if error else None,
            error_message=str(error)[:512] if error else None,
        )

    def _emit_sync(self, event: TelemetryEvent) -> None:
        emit_sync = getattr(self.sink, "emit_sync", None)
        if callable(emit_sync):
            try:
                emit_sync(event)
            except Exception:
                return
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            try:
                asyncio.run(self._emit_async(event))
            except Exception:
                return
        else:
            loop.create_task(self._emit_async(event))

    async def _emit_async(self, event: TelemetryEvent) -> None:
        try:
            result = self.sink.emit(event)
            if inspect.isawaitable(result):
                await result
        except Exception:
            return


def build_default_observability() -> ObservabilityService:
    max_events = _positive_int(os.getenv("OBSERVABILITY_BUFFER_SIZE"), 1000)
    local = LocalJsonLogSink(max_events=max_events)
    sink = FutureAGISink(FutureAGIConfig.from_env(), fallback=local)
    return ObservabilityService(sink, local_sink=local)


_service: ObservabilityService | None = None


def get_observability() -> ObservabilityService:
    global _service
    if _service is None:
        _service = build_default_observability()
    return _service


def set_observability(service: ObservabilityService) -> None:
    global _service
    _service = service


def _positive_int(raw: str | None, default: int) -> int:
    try:
        value = int(raw) if raw is not None else default
    except ValueError:
        return default
    return value if value > 0 else default
