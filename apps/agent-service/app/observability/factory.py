"""Construction and process-wide access for the observability service."""

from __future__ import annotations

import os

from .futureagi import FutureAGIConfig, FutureAGISink
from .local import LocalJsonLogSink
from .service import ObservabilityService
from .utils import positive_float, positive_int


def build_default_observability(
    *,
    max_pending_tasks: int | None = None,
    pending_flush_timeout_seconds: float | None = None,
) -> ObservabilityService:
    max_events = positive_int(os.getenv("OBSERVABILITY_BUFFER_SIZE"), 1000)
    local = LocalJsonLogSink(max_events=max_events)
    sink = FutureAGISink(FutureAGIConfig.from_env(), fallback=local)
    return ObservabilityService(
        sink,
        local_sink=local,
        max_pending_tasks=max_pending_tasks
        if max_pending_tasks is not None
        else positive_int(os.getenv("OBSERVABILITY_MAX_PENDING_TASKS"), 256),
        pending_flush_timeout_seconds=pending_flush_timeout_seconds
        if pending_flush_timeout_seconds is not None
        else positive_float(os.getenv("OBSERVABILITY_PENDING_FLUSH_TIMEOUT_SECONDS"), 2.0),
    )


_service: ObservabilityService | None = None


def get_observability() -> ObservabilityService:
    global _service
    if _service is None:
        _service = build_default_observability()
    return _service


def set_observability(service: ObservabilityService) -> None:
    global _service
    _service = service


__all__ = ["build_default_observability", "get_observability", "set_observability"]
