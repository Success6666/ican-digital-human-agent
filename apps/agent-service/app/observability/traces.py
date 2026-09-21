"""Trace grouping and sanitised replay views for the evaluation console."""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

from .models import TelemetryEvent, TracePhase, TraceReplay, TraceStage, TraceSummary
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

# End-to-end phases of the voice loop, in the order a turn actually happens.
# Matching is by name prefix so a new marker inside an existing phase is picked
# up without having to extend this table.
_PHASE_ORDER: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("capture", "采集", ("capture.",)),
    ("asr", "识别", ("asr.", "realtime.first_transcript")),
    ("agent", "理解", ("agent.", "security_gate", "receive", "realtime.run_started")),
    ("speech", "装配", ("speech.", "realtime.first_delta", "realtime.audio_queue", "send_text")),
    ("playback", "播报", ("speak.", "ttsa.", "realtime.first_audio_output", "realtime.interrupt_ack")),
)

_PHASE_LABELS = {key: label for key, label, _ in _PHASE_ORDER}

# A phase is browser-owned when only the client can observe it. Recognition is
# server-observable now that the ASR ingress emits its own markers, so it is
# intentionally absent here and counts as covered for server-origin traces.
_BROWSER_PHASES = {"capture", "speech", "playback"}


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
    # Summarise the sanitised set so a redacted credential can never reach the
    # waterfall through an error message or attribute.
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
    phases = _phases(ordered, started_at)
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
        phases=phases,
        origin=_origin(ordered),
        coverage=[phase.key for phase in phases if phase.observed],
    )


def _phases(events: list[TelemetryEvent], started_at: Any) -> list[TracePhase]:
    """Bucket trace events into the five end-to-end phases of one turn.

    Every phase is always returned, including unobserved ones, so the console
    shows a gap instead of silently hiding a stage the browser never reported.
    """

    buckets: dict[str, list[TelemetryEvent]] = {key: [] for key, _, _ in _PHASE_ORDER}
    for event in events:
        key = _phase_for(event.name)
        if key is not None:
            buckets[key].append(event)

    phases: list[TracePhase] = []
    for key, label, _ in _PHASE_ORDER:
        items = buckets[key]
        if not items:
            phases.append(TracePhase(key=key, label=label, start_offset_ms=0.0, observed=False))  # type: ignore[arg-type]
            continue
        first = items[0]
        last = items[-1]
        statuses = {item.status for item in items}
        status = "error" if "error" in statuses else ("ok" if "ok" in statuses else "unset")
        error_event = next((item for item in items if item.status == "error"), None)
        failure = None
        if error_event is not None:
            failure = error_event.error_message or str(error_event.attributes.get("reason") or "") or None
        duration_ms = max(0.0, (last.timestamp - first.timestamp).total_seconds() * 1000)
        phases.append(
            TracePhase(
                key=key,  # type: ignore[arg-type]
                label=label,
                start_offset_ms=max(0.0, (first.timestamp - started_at).total_seconds() * 1000),
                # A single-marker phase has no measurable span; reporting 0.0
                # would misread as "instantaneous" in the waterfall.
                duration_ms=duration_ms if len(items) > 1 else None,
                status=status,  # type: ignore[arg-type]
                event_count=len(items),
                first_event_name=first.name,
                last_event_name=last.name,
                observed=True,
                error_message=failure or None,
            )
        )
    return phases


def _phase_for(name: str) -> str | None:
    normalized = name.casefold()
    for key, _, prefixes in _PHASE_ORDER:
        for prefix in prefixes:
            if normalized == prefix or normalized.startswith(prefix):
                return key
    return None


def _origin(events: list[TelemetryEvent]) -> str:
    """Label the trace by whether the browser contributed any marker."""

    for event in events:
        if event.attributes.get("source") == "browser":
            return "browser"
    return "server"



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
