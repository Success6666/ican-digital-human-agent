"""Public marker methods kept separate from the observability core facade."""

from __future__ import annotations

from .markers import record_first_visible as _record_first_visible
from .markers import record_interrupted as _record_interrupted


class ObservabilityMarkerMixin:
    """Expose bounded latency markers without coupling the service to storage."""

    def record_first_visible(
        self,
        trace_id: str,
        *,
        owner_id: str,
        latency_ms: float,
        source: str = "agent.sse",
    ) -> None:
        _record_first_visible(
            self,
            trace_id=trace_id,
            owner_id=owner_id,
            latency_ms=latency_ms,
            source=source,
        )

    def record_interrupted(
        self,
        trace_id: str,
        *,
        owner_id: str,
        reason: str,
        latency_ms: float | None = None,
        source: str = "agent.sse",
    ) -> None:
        _record_interrupted(
            self,
            trace_id,
            owner_id=owner_id,
            reason=reason,
            latency_ms=latency_ms,
            source=source,
        )


__all__ = ["ObservabilityMarkerMixin"]
