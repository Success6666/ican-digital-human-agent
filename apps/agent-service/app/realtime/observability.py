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
        self._utterance_started: dict[str, float] = {}
        self._markers: set[tuple[str, str]] = set()
        self._last_queue_at = 0.0
        self._last_dropped = -1
        self._last_asr_buffered_at = 0.0
        self._last_asr_dropped = -1
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

    def asr_started(
        self,
        *,
        utterance_id: str | None,
        revision: int | None,
        trace_id: str | None = None,
    ) -> None:
        """Mark the moment the server starts buffering one spoken turn.

        The utterance id is already the browser-side correlation key, so the
        capture phase becomes observable at the exact point audio begins to
        accumulate instead of only when a transcript finally arrives.
        """
        resolved = trace_id or self._utterance_trace(utterance_id)
        if utterance_id:
            self._utterance_started[utterance_id] = time.perf_counter()
            self._bound_map(self._utterance_started)
        self._record(
            "asr.capture_started",
            trace_id=resolved,
            attributes={
                "utterance_id": utterance_id,
                "revision": revision,
                "latency_ms": self._elapsed(),
            },
        )

    def asr_buffered(
        self,
        *,
        utterance_id: str | None,
        frames: int,
        received_bytes: int,
        buffered_bytes: int,
        dropped_frames: int,
        trace_id: str | None = None,
    ) -> None:
        """Record audio accumulation without emitting one event per frame."""
        resolved = trace_id or self._utterance_trace(utterance_id)
        dropped = max(0, dropped_frames)
        now = time.perf_counter()
        if dropped <= self._last_asr_dropped and now - self._last_asr_buffered_at < 0.5:
            return
        self._last_asr_buffered_at = now
        self._last_asr_dropped = max(self._last_asr_dropped, dropped)
        self._record(
            "asr.audio_buffered",
            trace_id=resolved,
            attributes={
                "utterance_id": utterance_id,
                "frames": frames,
                "received_bytes": received_bytes,
                "buffered_bytes": buffered_bytes,
                "dropped_frames": dropped_frames,
            },
        )

    def asr_finished(
        self,
        *,
        utterance_id: str | None,
        revision: int | None,
        status: str,
        reason: str | None,
        text_length: int,
        trace_id: str | None = None,
    ) -> None:
        """Close the recognition phase with a terminal status and duration."""
        resolved = trace_id or self._utterance_trace(utterance_id)
        started = self._utterance_started.pop(utterance_id or "", None)
        duration_ms = (
            round(max(0.0, (time.perf_counter() - started) * 1000), 2)
            if started is not None
            else None
        )
        name = "asr.failed" if status == "error" else "asr.finished"
        self._record(
            name,
            trace_id=resolved,
            attributes={
                "utterance_id": utterance_id,
                "revision": revision,
                "status": status,
                "reason": reason,
                "text_length": max(0, text_length),
                "duration_ms": duration_ms,
                "latency_ms": self._elapsed(),
            },
        )

    def _utterance_trace(self, utterance_id: str | None) -> str:
        """Correlate a spoken turn with whatever trace the browser announced.

        Browser audio arrives before `run_started`, so the connection id is the
        only stable key until the run claims the turn. Once a run trace exists
        it wins, keeping ASR on the same trace as the rest of the pipeline.
        """
        if utterance_id:
            for run_id, mapped in self._run_traces.items():
                if run_id and mapped:
                    return mapped
        return self.connection_id

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
        # The sink derives status from an exception object, not from attributes.
        # Without this a failed marker would be recorded as ``ok`` and the
        # console waterfall would hide a broken stage behind a green bar.
        error = _failure(values)
        try:
            recorder(
                name,
                event_type="realtime",
                trace_id=trace_id,
                attributes=values,
                **({"error": error} if error is not None else {}),
            )
        except Exception:
            return

    def _elapsed(self) -> float:
        return round(max(0.0, (time.perf_counter() - self.started_at) * 1000), 2)

    @staticmethod
    def _bound_map(values: dict[str, Any], limit: int = 512) -> None:
        while len(values) > limit:
            values.pop(next(iter(values)))


def _failure(attributes: dict[str, Any]) -> RuntimeError | None:
    """Turn a marker's own failure fields into the error object the sink wants.

    Realtime markers describe outcomes with ``status``/``reason`` instead of an
    exception, so this bridges the two representations without inventing a
    message where nothing actually failed.
    """
    if str(attributes.get("status", "")).casefold() != "error":
        return None
    reason = attributes.get("reason") or attributes.get("code") or "realtime_error"
    return RuntimeError(str(reason)[:512])


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
