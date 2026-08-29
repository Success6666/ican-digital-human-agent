"""Trace grouping and sanitised replay views for the evaluation console."""

from __future__ import annotations

from collections.abc import Iterable

from .models import TelemetryEvent, TraceReplay, TraceStage, TraceSummary
from .redaction import redact


def summaries(
    events: Iterable[TelemetryEvent],
    *,
    limit: int = 30,
    owner_id: str | None = None,
) -> list[TraceSummary]:
    grouped: dict[str, list[TelemetryEvent]] = {}
    for event in _scope(events, owner_id):
        grouped.setdefault(event.trace_id, []).append(event)
    result = [_summarize(items) for items in grouped.values() if items]
    result.sort(key=lambda item: item.ended_at, reverse=True)
    return result[: max(1, min(limit, 100))]


def replay(
    events: Iterable[TelemetryEvent],
    trace_id: str,
    *,
    owner_id: str | None = None,
) -> TraceReplay | None:
    selected = [event for event in _scope(events, owner_id) if event.trace_id == trace_id]
    if not selected:
        return None
    selected.sort(key=lambda item: item.timestamp)
    safe_events = [event.model_copy(update={"attributes": redact(event.attributes)}) for event in selected]
    return TraceReplay(trace=_summarize(safe_events), events=safe_events)


def _scope(events: Iterable[TelemetryEvent], owner_id: str | None) -> list[TelemetryEvent]:
    items = list(events)
    if owner_id is None:
        return items
    return [event for event in items if event.attributes.get("owner_id") == owner_id]


def _summarize(events: list[TelemetryEvent]) -> TraceSummary:
    ordered = sorted(events, key=lambda item: item.timestamp)
    started_at = ordered[0].timestamp
    ended_at = ordered[-1].timestamp
    statuses = {event.status for event in ordered}
    status = "error" if "error" in statuses else ("unset" if "unset" in statuses else "ok")
    stages = [
        TraceStage(
            name=event.name,
            event_type=event.event_type,
            status=event.status,
            duration_ms=event.duration_ms,
            timestamp=event.timestamp,
            error_message=event.error_message,
        )
        for event in ordered
    ]
    return TraceSummary(
        trace_id=ordered[0].trace_id,
        status=status,  # type: ignore[arg-type]
        started_at=started_at,
        ended_at=ended_at,
        duration_ms=max(0.0, (ended_at - started_at).total_seconds() * 1000),
        event_count=len(ordered),
        error_count=sum(1 for event in ordered if event.status == "error"),
        stages=stages,
    )
