"""ASR-side realtime telemetry: recognition must be traceable end to end."""

from __future__ import annotations

import logging

import pytest

from app.observability.futureagi import FutureAGIConfig, FutureAGISink
from app.observability.local import LocalJsonLogSink
from app.observability.service import ObservabilityService
from app.observability.traces import replay, summaries
from app.realtime.observability import RealtimeTelemetry


def _service() -> ObservabilityService:
    """Build a fully local observability service with no exporter attached."""
    local = LocalJsonLogSink(logger=logging.getLogger("test-realtime-observability"))
    sink = FutureAGISink(
        FutureAGIConfig(enabled=False),
        fallback=local,
        logger=logging.getLogger("test-realtime-futureagi"),
    )
    return ObservabilityService(sink, local_sink=local)


class _RecordingObserver:
    """Minimal stand-in for the observability service surface telemetry uses."""

    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def record_event(self, name, *, event_type="event", trace_id=None, attributes=None, **kwargs):
        del kwargs
        self.events.append(
            {
                "name": name,
                "event_type": event_type,
                "trace_id": trace_id,
                "attributes": dict(attributes or {}),
            }
        )

    def names(self) -> list[str]:
        return [str(event["name"]) for event in self.events]

    def find(self, name: str) -> dict[str, object]:
        for event in self.events:
            if event["name"] == name:
                return event
        raise AssertionError(f"{name} was not recorded; saw {self.names()}")

    def last(self, name: str) -> dict[str, object]:
        for event in reversed(self.events):
            if event["name"] == name:
                return event
        raise AssertionError(f"{name} was not recorded; saw {self.names()}")


def _telemetry(observer: _RecordingObserver | None, connection_id: str = "conn-1") -> RealtimeTelemetry:
    telemetry = RealtimeTelemetry(observer, connection_id)
    telemetry.bind(owner_id="u-asr", session_id="s-asr")
    return telemetry


def test_asr_capture_start_and_finish_form_one_measurable_span() -> None:
    observer = _RecordingObserver()
    telemetry = _telemetry(observer)

    telemetry.asr_started(utterance_id="utt-1", revision=2)
    telemetry.asr_finished(
        utterance_id="utt-1",
        revision=2,
        status="final",
        reason=None,
        text_length=len("帮我查一下天气"),
    )

    assert observer.names() == ["asr.capture_started", "asr.finished"]
    finished = observer.find("asr.finished")
    attributes = finished["attributes"]
    assert attributes["status"] == "final"
    assert attributes["text_length"] == 7
    assert attributes["utterance_id"] == "utt-1"
    assert attributes["revision"] == 2
    # Duration is derived from the matching started marker, not wall-clock luck.
    assert isinstance(attributes["duration_ms"], float)
    assert attributes["duration_ms"] >= 0
    # Both markers must share one trace so replay groups them together.
    assert {event["trace_id"] for event in observer.events} == {"conn-1"}


def test_asr_failure_is_reported_as_an_error_marker_with_its_reason() -> None:
    observer = _RecordingObserver()
    telemetry = _telemetry(observer)

    telemetry.asr_started(utterance_id="utt-2", revision=1)
    telemetry.asr_finished(
        utterance_id="utt-2",
        revision=1,
        status="error",
        reason="asr_unavailable",
        text_length=0,
    )

    assert "asr.failed" in observer.names()
    failed = observer.find("asr.failed")
    assert failed["attributes"]["reason"] == "asr_unavailable"
    assert failed["attributes"]["text_length"] == 0


def test_audio_buffering_is_rate_limited_instead_of_per_frame() -> None:
    observer = _RecordingObserver()
    telemetry = _telemetry(observer)

    for frames in range(1, 51):
        telemetry.asr_buffered(
            utterance_id="utt-3",
            frames=frames,
            received_bytes=frames * 640,
            buffered_bytes=frames * 640,
            dropped_frames=0,
        )

    # 50 frames a few microseconds apart must collapse to a single marker.
    assert observer.names().count("asr.audio_buffered") == 1
    buffered = observer.find("asr.audio_buffered")
    assert buffered["attributes"]["frames"] == 1


def test_dropped_frames_bypass_the_buffer_rate_limit() -> None:
    observer = _RecordingObserver()
    telemetry = _telemetry(observer)

    telemetry.asr_buffered(
        utterance_id="utt-4", frames=1, received_bytes=640, buffered_bytes=640, dropped_frames=0
    )
    telemetry.asr_buffered(
        utterance_id="utt-4", frames=2, received_bytes=1280, buffered_bytes=640, dropped_frames=3
    )

    # An increase in dropped frames is a real signal and must not be swallowed.
    assert observer.names().count("asr.audio_buffered") == 2
    assert observer.last("asr.audio_buffered")["attributes"]["dropped_frames"] == 3


def test_buffer_overflow_raises_one_explicit_truncation_marker() -> None:
    observer = _RecordingObserver()
    telemetry = _telemetry(observer)

    # Overflow hits mid-utterance; the periodic sample keeps flowing afterwards.
    telemetry.asr_buffered(
        utterance_id="utt-9", frames=10, received_bytes=6400, buffered_bytes=6400,
        dropped_frames=0, capacity_bytes=6400,
    )
    telemetry.asr_buffered(
        utterance_id="utt-9", frames=20, received_bytes=12800, buffered_bytes=6400,
        dropped_frames=10, capacity_bytes=6400,
    )
    telemetry.asr_buffered(
        utterance_id="utt-9", frames=30, received_bytes=19200, buffered_bytes=6400,
        dropped_frames=20, capacity_bytes=6400,
    )

    truncated = [event for event in observer.events if event["name"] == "asr.buffer_truncated"]
    # One utterance, one truncation marker: a per-frame event would drown the
    # trace, and a silent one is exactly the failure this marker exists to end.
    assert len(truncated) == 1
    attributes = truncated[0]["attributes"]
    assert attributes["reason"] == "audio_buffer_overflow"
    assert attributes["status"] == "error"
    assert attributes["dropped_frames"] == 10
    # Milliseconds are the human-facing unit the panel renders.
    assert attributes["dropped_ms"] == 200
    assert attributes["capacity_bytes"] == 6400
    assert truncated[0]["trace_id"] == "conn-1"


def test_truncation_marker_is_per_utterance_not_per_connection() -> None:
    observer = _RecordingObserver()
    telemetry = _telemetry(observer)

    telemetry.asr_buffered(
        utterance_id="utt-a", frames=20, received_bytes=12800, buffered_bytes=6400,
        dropped_frames=10, capacity_bytes=6400,
    )
    telemetry.asr_buffered(
        utterance_id="utt-b", frames=20, received_bytes=12800, buffered_bytes=6400,
        dropped_frames=10, capacity_bytes=6400,
    )

    # A later question overflowing on its own must be named on its own.
    assert observer.names().count("asr.buffer_truncated") == 2


def test_tts_drop_is_recorded_as_an_error_marker() -> None:
    observer = _RecordingObserver()
    telemetry = _telemetry(observer)

    telemetry.tts_dropped(run_id="run-77", reason="tts_queue_timeout", text_length=120)

    dropped = observer.find("realtime.tts_dropped")
    assert dropped["attributes"]["reason"] == "tts_queue_timeout"
    assert dropped["attributes"]["text_length"] == 120
    assert dropped["attributes"]["status"] == "error"
    assert dropped["attributes"]["run_id"] == "run-77"
    # The reply with holes must look broken in the console, not healthy.
    assert dropped["trace_id"] == "conn-1"


def test_asr_markers_follow_the_run_trace_once_a_run_is_known() -> None:
    observer = _RecordingObserver()
    telemetry = _telemetry(observer)

    telemetry.observe(
        {
            "type": "run_started",
            "runId": "run-9",
            "traceId": "browser-trace-9",
        }
    )
    # A later turn arrives before any run marker; it must still correlate to the
    # trace the browser announced rather than the bare connection id.
    telemetry.asr_started(utterance_id="utt-5", revision=1)
    telemetry.asr_finished(
        utterance_id="utt-5", revision=1, status="final", reason=None, text_length=2
    )

    assert observer.find("asr.capture_started")["trace_id"] == "browser-trace-9"
    assert observer.find("asr.finished")["trace_id"] == "browser-trace-9"


def test_unobserved_and_observed_phases_reflect_asr_markers() -> None:
    """Replay must classify server-side ASR markers into the recognition phase."""

    service = _service()
    telemetry = _telemetry(service, connection_id="conn-merge")
    telemetry.asr_started(utterance_id="utt-6", revision=1)
    telemetry.asr_finished(
        utterance_id="utt-6", revision=1, status="final", reason=None, text_length=5
    )

    summary = summaries(service.recent(), owner_id="u-asr")[0]
    phases = {phase.key: phase for phase in summary.phases}
    assert phases["asr"].observed is True
    assert phases["asr"].event_count == 2
    assert phases["asr"].status == "ok"
    assert phases["asr"].duration_ms is not None
    # Recognition is server-observable, so a server-origin trace covers it.
    assert summary.origin == "server"
    assert "asr" in summary.coverage
    # Phases the browser owns stay visible as gaps rather than being hidden.
    assert phases["capture"].observed is False
    assert phases["playback"].observed is False

    detail = replay(service.recent(), "conn-merge", owner_id="u-asr")
    assert detail is not None
    assert [event.name for event in detail.events] == ["asr.capture_started", "asr.finished"]


def test_failed_recognition_surfaces_the_reason_in_the_phase() -> None:
    service = _service()
    telemetry = _telemetry(service, connection_id="conn-fail")
    telemetry.asr_started(utterance_id="utt-7", revision=1)
    telemetry.asr_finished(
        utterance_id="utt-7", revision=1, status="error", reason="asr_timeout", text_length=0
    )

    summary = summaries(service.recent(), owner_id="u-asr")[0]
    phase = {item.key: item for item in summary.phases}["asr"]
    assert phase.status == "error"
    assert phase.error_message == "asr_timeout"
    assert summary.status == "error"


def test_telemetry_without_an_observer_is_silent() -> None:
    telemetry = _telemetry(None)
    # No observer must degrade to a no-op rather than raising on the audio path.
    telemetry.asr_started(utterance_id="utt-8", revision=1)
    telemetry.asr_buffered(
        utterance_id="utt-8", frames=1, received_bytes=640, buffered_bytes=640, dropped_frames=0
    )
    telemetry.asr_finished(
        utterance_id="utt-8", revision=1, status="empty", reason="asr_empty", text_length=0
    )
