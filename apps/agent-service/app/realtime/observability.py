"""Low-overhead transport telemetry for one realtime WebSocket."""

from __future__ import annotations

import time
from typing import Any


class RealtimeTelemetry:
    """Record bounded, provider-neutral transport markers.

    Graph spans already describe Agent work. This companion keeps connection
    and browser-facing milestones on the same trace when a run id is known,
    while using the connection id as a standalone trace for handshake events.
    """

    def __init__(self, observer: Any | None, connection_id: str) -> None:
        self.observer = observer
        self.connection_id = connection_id
        self.owner_id: str | None = None
        self.session_id: str | None = None
        self.started_at = time.perf_counter()
        self._run_started: dict[str, float] = {}
        self._run_traces: dict[str, str] = {}
        self._markers: set[tuple[str, str]] = set()
        self._last_queue_at = 0.0
        self._last_dropped = -1
        self._closed = False

    def bind(self, *, owner_id: str, session_id: str) -> None:
        self.owner_id = owner_id
        self.session_id = session_id

    def ready(self) -> None:
        self._record(
            "realtime.ready",
            trace_id=self.connection_id,
            attributes={"latency_ms": self._elapsed()},
        )

    def observe(
        self,
        event: dict[str, Any],
        *,
        enqueued: bool = True,
        queue_depth: int | None = None,
    ) -> None:
        kind = str(event.get("type", "")).casefold()
        run_id = _text(event.get("runId"))
        event_trace = _text(event.get("traceId"))
        trace_id = event_trace or (
            self._run_traces.get(run_id or "") if run_id else None
        )
        trace_id = trace_id or self.connection_id
        if run_id and event_trace:
            self._run_traces[run_id] = event_trace
        if kind == "run_started" and run_id:
            self._run_started[run_id] = time.perf_counter()
            self._run_traces[run_id] = trace_id
            self._bound_map(self._run_started)
            self._bound_map(self._run_traces)
            self._record("realtime.run_started", trace_id=trace_id, run_id=run_id)
        elif kind == "transcript":
            self._first(
                "transcript",
                trace_id,
                "realtime.first_transcript",
                {"status": _text(event.get("status")) or "unknown"},
            )
        elif kind in {"delta", "message", "assistant"}:
            self._first("delta", trace_id, "realtime.first_delta", {})
        elif kind == "audio_queue":
            self._queue(trace_id, event, enqueued=enqueued, queue_depth=queue_depth)
        elif kind == "ack" and str(event.get("action", "")).casefold() == "interrupt":
            accepted = bool(event.get("accepted"))
            started = self._run_started.get(run_id or "")
            self._record(
                "realtime.interrupt_ack",
                trace_id=trace_id,
                run_id=run_id,
                attributes={
                    "accepted": accepted,
                    "latency_ms": round(max(0.0, (time.perf_counter() - started) * 1000), 2)
                    if started is not None
                    else None,
                },
            )
        elif kind in {"interrupted", "run_done", "done"} and run_id:
            self._record(
                "realtime.run_terminal",
                trace_id=trace_id,
                run_id=run_id,
                attributes={"status": _text(event.get("status")) or kind},
            )
            if kind in {"run_done", "done"}:
                self._run_started.pop(run_id, None)
                self._run_traces.pop(run_id, None)

    def binary_output(self, size: int, *, run_id: str | None = None) -> None:
        if size <= 0:
            return
        trace_id = self._run_traces.get(run_id or "", self.connection_id)
        self._first(
            "audio",
            trace_id,
            "realtime.first_audio_output",
            {"bytes": size, "run_id": run_id},
        )

    def closed(self, *, code: int) -> None:
        if self._closed:
            return
        self._closed = True
        self._record(
            "realtime.closed",
            trace_id=self.connection_id,
            attributes={"close_code": code, "latency_ms": self._elapsed()},
        )

    def _queue(
        self,
        trace_id: str,
        event: dict[str, Any],
        *,
        enqueued: bool,
        queue_depth: int | None,
    ) -> None:
        dropped = _number(event.get("droppedFrames")) or 0
        now = time.perf_counter()
        if dropped <= self._last_dropped and now - self._last_queue_at < 0.25:
            return
        self._last_queue_at = now
        self._last_dropped = max(self._last_dropped, dropped)
        self._record(
            "realtime.audio_queue",
            trace_id=trace_id,
            attributes={
                "frames": _number(event.get("frames")) or 0,
                "buffered_bytes": _number(event.get("bufferedBytes")) or 0,
                "dropped_frames": dropped,
                "enqueued": enqueued,
                "queue_depth": max(0, queue_depth or 0),
            },
        )

    def _first(self, marker: str, trace_id: str, name: str, attributes: dict[str, Any]) -> None:
        key = (marker, trace_id)
        if key in self._markers:
            return
        self._markers.add(key)
        while len(self._markers) > 2048:
            self._markers.pop()
        self._record(name, trace_id=trace_id, attributes={"latency_ms": self._elapsed(), **attributes})

    def _record(
        self,
        name: str,
        *,
        trace_id: str,
        run_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        recorder = getattr(self.observer, "record_event_nonblocking", None)
        if not callable(recorder):
            recorder = getattr(self.observer, "record_event", None)
        if not callable(recorder):
            return
        values = {
            "owner_id": self.owner_id,
            "session_id": self.session_id,
            "connection_id": self.connection_id,
            "run_id": run_id,
            **(attributes or {}),
        }
        try:
            recorder(name, event_type="realtime", trace_id=trace_id, attributes=values)
        except Exception:
            return

    def _elapsed(self) -> float:
        return round(max(0.0, (time.perf_counter() - self.started_at) * 1000), 2)

    @staticmethod
    def _bound_map(values: dict[str, Any], limit: int = 512) -> None:
        while len(values) > limit:
            values.pop(next(iter(values)))


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    clean = value.strip()
    return clean[:128] if clean else None


def _number(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, number)


__all__ = ["RealtimeTelemetry"]
