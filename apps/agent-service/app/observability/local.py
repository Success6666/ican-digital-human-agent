"""Local JSON-lines sink used when FutureAGI is unavailable or unhealthy."""

from __future__ import annotations

from collections import deque
import json
import logging
import threading

from .models import TelemetryEvent
from .redaction import redact


class LocalJsonLogSink:
    def __init__(self, *, logger: logging.Logger | None = None, max_events: int = 1000) -> None:
        if max_events < 1:
            raise ValueError("max_events must be positive")
        self.logger = logger or logging.getLogger("ican.agent.observability")
        self._events: deque[TelemetryEvent] = deque(maxlen=max_events)
        self._lock = threading.Lock()

    @property
    def backend(self) -> str:
        return "local"

    @property
    def configured(self) -> bool:
        return True

    @property
    def last_error(self) -> str | None:
        return None

    async def emit(self, event: TelemetryEvent) -> None:
        self.record_sync(event)

    def record_sync(self, event: TelemetryEvent) -> None:
        """Record immediately for low-latency local diagnostics.

        Span lifecycle hooks are synchronous, so keeping the bounded buffer
        synchronous makes recent events available before the next event-loop
        tick while the remote exporter remains asynchronous.
        """
        safe_attributes = redact(event.attributes)
        safe_event = event.model_copy(update={"attributes": safe_attributes})
        with self._lock:
            self._events.append(safe_event)
        payload = safe_event.model_dump(mode="json")
        self.logger.info(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str))

    async def flush(self) -> None:
        return None

    def recent(self, limit: int = 100) -> list[TelemetryEvent]:
        limit = max(0, min(limit, len(self._events)))
        with self._lock:
            return list(self._events)[-limit:] if limit else []

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)
