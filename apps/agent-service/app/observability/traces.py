"""Trace grouping and sanitised replay views for the evaluation console."""

from __future__ import annotations

from collections.abc import Iterable
import math
from typing import Any

from .models import TelemetryEvent, TraceReplay, TraceStage, TraceSummary
from .redaction import redact


DEFAULT_MAX_REPLAY_EVENTS = 500

_FIRST_EVENT_NAMES = {"agent.first_byte", "stream.first_event", "first_event"}
_FIRST_VISIBLE_NAMES = {"agent.first_visible", "stream.first_visible", "first_visible"}
_AGENT_NAMES = {"agent.invoke", "agent.stream", "agent.completed", "agent.complete"}
_DIGITAL_HUMAN_NAMES = {"provider", "send_text", "digital_human", "avatar"}
_CANCEL_NAMES = {
    "cancel",
    "cancelled",
    "cancellation",
    "interrupt",
    "interrupted",
    "run.stop",
    "run.interrupted",
}


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
    max_events: int = DEFAULT_MAX_REPLAY_EVENTS,
) -> TraceReplay | None:
    selected = [event for event in _scope(events, owner_id) if event.trace_id == trace_id]
    if not selected:
        return None
    ordered = _ordered(selected)
    safe_limit = max(1, min(max_events, DEFAULT_MAX_REPLAY_EVENTS))
    truncated = len(ordered) > safe_limit
    visible = ordered[:safe_limit]
    safe_events = [event.model_copy(update={"attributes": redact(event.attributes)}) for event in visible]
    return TraceReplay(trace=_summarize(safe_events), events=safe_events, truncated=truncated)


def _scope(events: Iterable[TelemetryEvent], owner_id: str | None) -> list[TelemetryEvent]:
    items = list(events)
    if owner_id is None:
        return items
    return [event for event in items if event.attributes.get("owner_id") == owner_id]


def _summarize(events: list[TelemetryEvent]) -> TraceSummary:
    ordered = _ordered(events)
    started_at = ordered[0].timestamp
    ended_at = ordered[-1].timestamp
    statuses = {event.status for event in ordered}
    # ``span.start`` is intentionally ``unset`` while a span is in flight.
    # A completed trace also contains an ``ok`` end event, so lifecycle start
    # markers must not downgrade an otherwise successful trace to ``unset``.
    status = "error" if "error" in statuses else ("ok" if "ok" in statuses else "unset")
    cancelled = any(_is_cancelled(event) for event in ordered)
    stages = [
        TraceStage(
            name=event.name,
            sequence=event.sequence,
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
        cancelled=cancelled,
        first_event_latency_ms=_latency_value(ordered, _FIRST_EVENT_NAMES, ("first_event_latency_ms", "first_byte_latency_ms", "latency_ms")),
        first_visible_latency_ms=_latency_value(ordered, _FIRST_VISIBLE_NAMES, ("first_visible_latency_ms", "visible_latency_ms", "latency_ms")),
        agent_latency_ms=_stage_latency(ordered, _AGENT_NAMES, ("agent_latency_ms", "agentLatencyMs")),
        digital_human_latency_ms=_stage_latency(
            ordered,
            _DIGITAL_HUMAN_NAMES,
            ("digital_human_latency_ms", "digitalHumanLatencyMs", "avatar_latency_ms"),
        ),
        cancellation_latency_ms=_latency_value(
            ordered,
            _CANCEL_NAMES,
            ("cancellation_latency_ms", "cancel_latency_ms", "cancelLatencyMs", "latency_ms"),
        ),
        stages=stages,
    )


def _ordered(events: Iterable[TelemetryEvent]) -> list[TelemetryEvent]:
    """Order by wall time and then the process-local sequence number."""

    return sorted(events, key=lambda item: (item.timestamp, item.sequence))


def _latency_value(
    events: list[TelemetryEvent],
    names: set[str],
    attributes: tuple[str, ...],
) -> float | None:
    values: list[float] = []
    for event in events:
        normalized_name = event.name.casefold()
        if event.name not in names and not any(part in normalized_name for part in names):
            continue
        value = _attribute_number(event.attributes, attributes)
        if value is not None:
            values.append(value)
        elif event.duration_ms is not None and event.event_type != "span.start":
            values.append(event.duration_ms)
    return round(min(values), 2) if values else None


def _stage_latency(
    events: list[TelemetryEvent],
    names: set[str],
    attributes: tuple[str, ...],
) -> float | None:
    values: list[float] = []
    for event in events:
        normalized_name = event.name.casefold()
        if not any(part in normalized_name for part in names):
            continue
        value = _attribute_number(event.attributes, attributes)
        if value is not None:
            values.append(value)
        elif event.duration_ms is not None and event.event_type != "span.start":
            values.append(event.duration_ms)
    return round(min(values), 2) if values else None


def _attribute_number(attributes: dict[str, Any], names: tuple[str, ...]) -> float | None:
    for name in names:
        value = attributes.get(name)
        if isinstance(value, bool):
            continue
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(parsed) and parsed >= 0:
            return parsed
    return None


def _is_cancelled(event: TelemetryEvent) -> bool:
    attributes = event.attributes
    if any(bool(attributes.get(key)) for key in ("cancelled", "canceled", "interrupted")):
        return True
    if (event.error_type or "").casefold() in {"cancellederror", "runinterrupted"}:
        return True
    normalized = f"{event.name}.{event.event_type}".casefold()
    return any(part in normalized for part in _CANCEL_NAMES)
