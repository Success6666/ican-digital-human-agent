"""Bounded first-visible and interruption markers."""

from __future__ import annotations

from typing import Any

from .utils import latency_value


def record_first_visible(
    service: Any,
    trace_id: str,
    *,
    owner_id: str,
    latency_ms: float,
    source: str = "agent.sse",
) -> None:
    record_marker(
        service,
        "agent.first_visible",
        trace_id=trace_id,
        owner_id=owner_id,
        latency_ms=latency_ms,
        source=source,
    )


def record_interrupted(
    service: Any,
    trace_id: str,
    *,
    owner_id: str,
    reason: str,
    latency_ms: float | None = None,
    source: str = "agent.sse",
) -> None:
    if not claim_marker(service, f"agent.interrupted:{trace_id}"):
        return
    attributes: dict[str, Any] = {
        "owner_id": owner_id,
        "reason": str(reason)[:64],
        "source": str(source)[:64],
        "cancelled": True,
        "interrupted": True,
    }
    normalized = latency_value(latency_ms)
    if normalized is not None:
        attributes["latency_ms"] = normalized
        attributes["cancellation_latency_ms"] = normalized
    service.record_event_nonblocking(
        "run.interrupted",
        event_type="latency",
        trace_id=trace_id,
        attributes=attributes,
    )


def record_marker(
    service: Any,
    name: str,
    *,
    trace_id: str,
    owner_id: str,
    latency_ms: float,
    source: str,
) -> None:
    normalized = latency_value(latency_ms)
    if normalized is None:
        return
    if not claim_marker(service, f"{name}:{trace_id}"):
        return
    service.record_event_nonblocking(
        name,
        event_type="latency",
        trace_id=trace_id,
        attributes={
            "owner_id": owner_id,
            "latency_ms": normalized,
            "source": str(source)[:64],
        },
    )


def claim_marker(service: Any, key: str) -> bool:
    with service._pending_lock:
        markers = service._marker_keys
        if key in markers:
            return False
        if len(markers) >= 4096:
            markers.pop()
        markers.add(key)
        return True


__all__ = ["claim_marker", "record_first_visible", "record_interrupted", "record_marker"]
