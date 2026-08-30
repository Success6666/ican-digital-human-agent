"""Provider-neutral observer callbacks used by the graph runtime."""

from __future__ import annotations

from typing import Any


def record_first_byte(observer: Any | None, trace_id: str, *, owner_id: str, latency_ms: float) -> None:
    record_marker(observer, "agent.first_byte", trace_id=trace_id, owner_id=owner_id, latency_ms=latency_ms)


def record_first_visible(observer: Any | None, trace_id: str, *, owner_id: str, latency_ms: float) -> None:
    if observer is None:
        return
    recorder = getattr(observer, "record_first_visible", None)
    if callable(recorder):
        try:
            recorder(trace_id, owner_id=owner_id, latency_ms=latency_ms)
        except Exception:
            return
        return
    record_marker(observer, "agent.first_visible", trace_id=trace_id, owner_id=owner_id, latency_ms=latency_ms)


def record_interrupted(
    observer: Any | None,
    trace_id: str,
    *,
    owner_id: str,
    reason: str,
    latency_ms: float | None = None,
) -> None:
    if observer is None:
        return
    recorder = getattr(observer, "record_interrupted", None)
    if callable(recorder):
        try:
            recorder(trace_id, owner_id=owner_id, reason=reason, latency_ms=latency_ms)
        except Exception:
            return
        return
    attributes: dict[str, Any] = {
        "owner_id": owner_id,
        "reason": reason[:64],
        "cancelled": True,
        "interrupted": True,
    }
    if latency_ms is not None:
        attributes["latency_ms"] = round(latency_ms, 2)
        attributes["cancellation_latency_ms"] = round(latency_ms, 2)
    record_observer_event(
        observer,
        "run.interrupted",
        trace_id=trace_id,
        event_type="latency",
        attributes=attributes,
    )


def record_marker(observer: Any | None, name: str, *, trace_id: str, owner_id: str, latency_ms: float) -> None:
    if observer is None:
        return
    record_observer_event(
        observer,
        name,
        trace_id=trace_id,
        event_type="latency",
        attributes={"owner_id": owner_id, "latency_ms": round(latency_ms, 2)},
    )


def record_observer_event(
    observer: Any | None,
    name: str,
    *,
    trace_id: str,
    event_type: str,
    attributes: dict[str, Any],
) -> None:
    if observer is None:
        return
    recorder = getattr(observer, "record_event_nonblocking", None)
    if not callable(recorder):
        recorder = getattr(observer, "record_event", None)
    if not callable(recorder):
        return
    try:
        recorder(name, event_type=event_type, trace_id=trace_id, attributes=attributes)
    except Exception:
        return


__all__ = [
    "record_first_byte",
    "record_first_visible",
    "record_interrupted",
    "record_marker",
    "record_observer_event",
]
