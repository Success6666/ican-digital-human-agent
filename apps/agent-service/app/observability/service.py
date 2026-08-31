"""Context-aware trace/span facade for graph, MCP, RAG and providers."""

from __future__ import annotations

import asyncio
import threading
from typing import Any
from uuid import uuid4

from .local import LocalJsonLogSink
from .models import ObservabilityHealth, TelemetryEvent, TraceReplay, TraceSummary
from .ports import EventSink
from .span import Span, _current_span, _current_trace
from .traces import replay as replay_trace
from .traces import summaries as summarize_traces
from .marker_api import ObservabilityMarkerMixin
from .transport import emit_async as _emit_async_transport
from .transport import emit_sync as _emit_sync_transport
from .transport import flush_pending as _flush_pending_transport
from .transport import pending_task_count as _pending_task_count
from .transport import schedule_async as _schedule_async_transport

# Keep Span available from the original import path for downstream callers.
__all__ = [
    "ObservabilityService",
    "Span",
    "build_default_observability",
    "get_observability",
    "set_observability",
]


class ObservabilityService(ObservabilityMarkerMixin):
    """Emit provider-neutral telemetry and expose bounded diagnostic views."""

    def __init__(
        self,
        sink: EventSink,
        *,
        local_sink: LocalJsonLogSink | None = None,
        max_pending_tasks: int = 256,
        pending_flush_timeout_seconds: float = 2.0,
    ) -> None:
        if max_pending_tasks < 1:
            raise ValueError("max_pending_tasks must be positive")
        if pending_flush_timeout_seconds <= 0:
            raise ValueError("pending_flush_timeout_seconds must be positive")
        self.sink = sink
        self.local_sink = local_sink
        self._sequence = 0
        self._sequence_lock = threading.Lock()
        self.max_pending_tasks = max_pending_tasks
        self.pending_flush_timeout_seconds = pending_flush_timeout_seconds
        self._pending_tasks: set[asyncio.Task[Any]] = set()
        self._pending_lock = threading.Lock()
        self._dropped_events = 0
        self._marker_keys: set[str] = set()

    def start_trace(
        self,
        name: str = "agent.request",
        attributes: dict[str, Any] | None = None,
        *,
        trace_id: str | None = None,
    ) -> Span:
        """Start a trace, optionally continuing an id owned by the caller."""

        return Span(self, name=name, event_type="trace", trace_id=trace_id, attributes=attributes)

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

    def record_event_nonblocking(
        self,
        name: str,
        *,
        event_type: str = "event",
        attributes: dict[str, Any] | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
        error: Exception | None = None,
    ) -> None:
        """Record an event without running exporter I/O on the request task."""

        event = self._stamp(
            self._make_event(
                name,
                event_type=event_type,
                attributes=attributes,
                trace_id=trace_id,
                span_id=span_id,
                error=error,
            )
        )
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._emit_sync(event)
        else:
            _schedule_async_transport(self, loop, event)

    async def arecord_event(self, *args: Any, **kwargs: Any) -> None:
        event = self._stamp(self._make_event(*args, **kwargs))
        await self._emit_async(event)

    def health(self) -> ObservabilityHealth:
        backend = getattr(self.sink, "backend", "unknown")
        configured = bool(getattr(self.sink, "configured", False))
        last_error = getattr(self.sink, "last_error", None)
        buffered = len(self.local_sink) if self.local_sink is not None else 0
        pending = self.pending_task_count
        return ObservabilityHealth(
            status="degraded" if backend == "local" and not configured else "ok",
            backend=backend,
            configured=configured,
            buffered_events=buffered,
            pending_tasks=pending,
            dropped_events=self.dropped_events,
            last_error=last_error,
        )

    @property
    def pending_task_count(self) -> int:
        """Return the number of in-flight asynchronous sink tasks."""

        return _pending_task_count(self)

    @property
    def dropped_events(self) -> int:
        """Number of events dropped after the asynchronous bound was reached."""

        with self._pending_lock:
            return self._dropped_events

    def recent(self, limit: int = 100, *, owner_id: str | None = None) -> list[TelemetryEvent]:
        if self.local_sink is None:
            return []
        if owner_id is not None:
            return self.local_sink.recent_for_owner(owner_id, limit)
        return self.local_sink.recent(limit)

    def trace_summaries(self, *, limit: int = 30, owner_id: str | None = None) -> list[TraceSummary]:
        """Group buffered events into bounded, user-facing trace summaries."""
        return summarize_traces(self.recent(1000, owner_id=owner_id), limit=limit)

    def trace_replay(self, trace_id: str, *, owner_id: str | None = None) -> TraceReplay | None:
        """Return a sanitized, ordered event sequence for one trace."""
        return replay_trace(self.recent(1000, owner_id=owner_id), trace_id)

    async def flush(self) -> None:
        await _flush_pending_transport(self)
        await self.sink.flush()

    async def reconfigure(self, configuration: Any) -> None:
        """Swap the optional exporter without dropping the local trace buffer."""

        from .futureagi import FutureAGIConfig, FutureAGISink

        await self.sink.flush()
        self.sink = FutureAGISink(
            FutureAGIConfig(
                enabled=bool(getattr(configuration, "enabled", False)),
                api_key=getattr(configuration, "api_key", None) or None,
                secret_key=getattr(configuration, "secret_key", None) or None,
                project=getattr(configuration, "project", "ican-digital-human"),
                endpoint=getattr(configuration, "endpoint", None) or None,
            ),
            fallback=self.local_sink,
        )

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
        _emit_sync_transport(self, event)

    async def _emit_async(self, event: TelemetryEvent, *, mirror: bool = True) -> None:
        await _emit_async_transport(self, event, mirror=mirror)

    def _mirror_local_if_needed(self, event: TelemetryEvent) -> None:
        """Mirror events unless the sink already owns the same local buffer."""

        if self.local_sink is None:
            return
        if self.sink is self.local_sink or getattr(self.sink, "local_sink", None) is self.local_sink:
            return
        self._record_local(event)

    def _record_local(self, event: TelemetryEvent) -> None:
        if self.local_sink is None:
            return
        try:
            self.local_sink.record_sync(event, emit_log=False)
        except TypeError:
            # Keep compatibility with caller-owned sinks that predate the
            # ``emit_log`` optimization.
            try:
                self.local_sink.record_sync(event)
            except Exception:
                return
        except Exception:
            return

    def _stamp(self, event: TelemetryEvent) -> TelemetryEvent:
        """Assign one process-local order number shared by every sink."""

        if event.sequence:
            return event
        with self._sequence_lock:
            self._sequence += 1
            sequence = self._sequence
        return event.model_copy(update={"sequence": sequence})


def build_default_observability(
    *,
    max_pending_tasks: int | None = None,
    pending_flush_timeout_seconds: float | None = None,
) -> ObservabilityService:
    # Keep the historical import path while implementation lives in factory.
    from .factory import build_default_observability as _build

    return _build(
        max_pending_tasks=max_pending_tasks,
        pending_flush_timeout_seconds=pending_flush_timeout_seconds,
    )


def get_observability() -> ObservabilityService:
    from .factory import get_observability as _get

    return _get()


def set_observability(service: ObservabilityService) -> None:
    from .factory import set_observability as _set

    _set(service)
