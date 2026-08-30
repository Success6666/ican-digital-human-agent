from __future__ import annotations

import json

import pytest

from app.api.sse import iter_sse_frames


class _Request:
    def __init__(self, disconnected: bool = False) -> None:
        self.disconnected = disconnected

    async def is_disconnected(self) -> bool:
        return self.disconnected


class _Events:
    def __init__(self, values: list[dict[str, object]], error: Exception | None = None) -> None:
        self.values = values
        self.error = error
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.values:
            return self.values.pop(0)
        if self.error is not None:
            error, self.error = self.error, None
            raise error
        raise StopAsyncIteration

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_sse_envelope_drops_stale_events_and_assigns_order() -> None:
    events = _Events(
        [
            {"event": "start", "data": {"traceId": "trace", "runId": "run-a"}},
            {"event": "delta", "data": {"traceId": "trace", "runId": "run-b", "text": "stale"}},
            {"event": "delta", "data": {"traceId": "trace", "runId": "run-a", "text": "ok", "eventId": "forged"}},
            {"event": "done", "data": {"traceId": "trace", "runId": "run-a"}},
            {"event": "delta", "data": {"traceId": "trace", "runId": "run-a", "text": "late"}},
        ]
    )

    frames = [frame async for frame in iter_sse_frames(events, _Request(), session_id="session")]

    assert [frame.split("\n", 2)[1] for frame in frames] == ["event:start", "event:delta", "event:done"]
    payloads = [json.loads(frame.split("data:", 1)[1]) for frame in frames]
    assert [item["seq"] for item in payloads] == [1, 2, 3]
    assert [item["eventId"] for item in payloads] == ["trace:1", "trace:2", "trace:3"]
    assert events.closed is True


@pytest.mark.asyncio
async def test_sse_drops_late_event_that_switches_trace() -> None:
    events = _Events(
        [
            {"event": "start", "data": {"traceId": "trace-a", "runId": "run"}},
            {"event": "delta", "data": {"traceId": "trace-b", "runId": "run", "text": "污染"}},
            {"event": "done", "data": {"traceId": "trace-a", "runId": "run", "reply": "完成"}},
        ]
    )

    frames = [frame async for frame in iter_sse_frames(events, _Request(), session_id="session")]

    assert [frame.split("\n", 2)[1] for frame in frames] == ["event:start", "event:done"]
    payloads = [json.loads(frame.split("data:", 1)[1]) for frame in frames]
    assert {item["traceId"] for item in payloads} == {"trace-a"}


@pytest.mark.asyncio
async def test_sse_source_error_has_terminal_done_and_closes_source() -> None:
    events = _Events([], error=RuntimeError("hidden sdk detail"))

    frames = [frame async for frame in iter_sse_frames(events, _Request(), session_id="session")]

    assert "event:error" in frames[0]
    assert "event:done" in frames[1]
    assert "hidden sdk detail" not in "".join(frames)
    assert events.closed is True


@pytest.mark.asyncio
async def test_sse_interrupted_is_preserved_when_source_ends_without_done() -> None:
    events = _Events([{"event": "interrupted", "data": {"runId": "run"}}])

    frames = [frame async for frame in iter_sse_frames(events, _Request(), session_id="session")]

    assert "event:interrupted" in frames[0]
    assert "event:done" in frames[1]
    done = json.loads(frames[1].split("data:", 1)[1])
    assert done["interrupted"] is True
    assert done["reply"] == "请求已打断。"


@pytest.mark.asyncio
async def test_sse_interrupted_is_preserved_when_source_raises_after_event() -> None:
    events = _Events(
        [{"event": "interrupted", "data": {"runId": "run"}}],
        error=RuntimeError("late source failure"),
    )

    frames = [frame async for frame in iter_sse_frames(events, _Request(), session_id="session")]

    assert ["event:interrupted" in frames[0], "event:done" in frames[1]] == [True, True]
    assert "event:error" not in "".join(frames)
    done = json.loads(frames[1].split("data:", 1)[1])
    assert done["interrupted"] is True


@pytest.mark.asyncio
async def test_sse_oversized_done_keeps_interrupted_semantics() -> None:
    events = _Events(
        [
            {"event": "interrupted", "data": {"runId": "run"}},
            {
                "event": "done",
                "data": {"runId": "run", "interrupted": True, "reply": "x" * (300 * 1024)},
            },
        ]
    )

    frames = [frame async for frame in iter_sse_frames(events, _Request(), session_id="session")]

    assert "event:interrupted" in frames[0]
    assert "event:done" in frames[1]
    done = json.loads(frames[1].split("data:", 1)[1])
    assert done["interrupted"] is True
    assert done["reply"] == "请求已打断。"


@pytest.mark.asyncio
async def test_sse_oversized_interrupted_keeps_event_type() -> None:
    events = _Events(
        [
            {
                "event": "interrupted",
                "data": {"runId": "run", "message": "x" * (300 * 1024)},
            }
        ]
    )

    frames = [frame async for frame in iter_sse_frames(events, _Request(), session_id="session")]

    assert "event:interrupted" in frames[0]
    interrupted = json.loads(frames[0].split("data:", 1)[1])
    assert interrupted["interrupted"] is True
    assert "event:done" in frames[1]


@pytest.mark.asyncio
async def test_sse_error_with_interrupted_flag_preserves_done_semantics() -> None:
    events = _Events([{"event": "error", "data": {"runId": "run", "interrupted": True}}])

    frames = [frame async for frame in iter_sse_frames(events, _Request(), session_id="session")]

    assert "event:error" in frames[0]
    done = json.loads(frames[1].split("data:", 1)[1])
    assert done["interrupted"] is True
    assert done["reply"] == "请求已打断。"


@pytest.mark.asyncio
async def test_sse_disconnect_stops_source_without_emitting_frames() -> None:
    events = _Events([{"event": "start", "data": {"runId": "run"}}])

    frames = [frame async for frame in iter_sse_frames(events, _Request(disconnected=True), session_id="session")]

    assert frames == []
    assert events.closed is True
