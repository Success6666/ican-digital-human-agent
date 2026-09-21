"""Local JSON-lines sink used when FutureAGI is unavailable or unhealthy."""

from __future__ import annotations

import json
import logging
import threading
from collections import deque

from .models import TelemetryEvent
from .redaction import redact


class LocalJsonLogSink:
    def __init__(self, *, logger: logging.Logger | None = None, max_events: int = 1000) -> None:
        if max_events < 1:
            raise ValueError("max_events must be positive")
        self.logger = logger or logging.getLogger("agent.observability")
        self._events: deque[TelemetryEvent] = deque(maxlen=max_events)
        self._lock = threading.Lock()
        self._sequence = 0
        self._event_ids: set[str] = set()

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

    def record_sync(self, event: TelemetryEvent, *, emit_log: bool = True) -> None:
        """Record immediately for low-latency local diagnostics.

        Span lifecycle hooks are synchronous, so keeping the bounded buffer
        synchronous makes recent events available before the next event-loop
        tick while the remote exporter remains asynchronous.
        """
        with self._lock:
            if event.event_id in self._event_ids:
                return
            self._sequence += 1
            if event.sequence:
                self._sequence = max(self._sequence, event.sequence)
            sequence = event.sequence or self._sequence
            safe_attributes = redact(event.attributes)
            safe_event = event.model_copy(update={"attributes": safe_attributes, "sequence": sequence})
            self._events.append(safe_event)
            self._event_ids.add(event.event_id)
            while len(self._event_ids) > self._events.maxlen:
                self._event_ids = {item.event_id for item in self._events}
        if emit_log:
            payload = safe_event.model_dump(mode="json")
            self.logger.info(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str))

    async def flush(self) -> None:
        return None

    def recent(self, limit: int = 100) -> list[TelemetryEvent]:
        with self._lock:
            limit = max(0, min(limit, len(self._events)))
            selected = list(self._events)[-limit:] if limit else []
            return [event.model_copy(deep=True) for event in selected]

    def recent_for_owner(self, owner_id: str, limit: int = 100) -> list[TelemetryEvent]:
        """Read a bounded owner-scoped snapshot without exposing other tenants."""

        safe_limit = max(0, min(limit, 500))
        if safe_limit == 0:
            return []
        with self._lock:
            # Iterate newest-first so a large mixed-tenant buffer does not
            # require copying and filtering the entire deque for each caller.
            selected: list[TelemetryEvent] = []
            for event in reversed(self._events):
                if event.attributes.get("owner_id") != owner_id:
                    continue
                selected.append(event.model_copy(deep=True))
                if len(selected) >= safe_limit:
                    break
            selected.reverse()
            return selected

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)
