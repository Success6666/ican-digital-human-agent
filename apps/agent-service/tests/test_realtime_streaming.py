from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from app.avatar.adapters.mock import MockProvider
from app.avatar.registry import ProviderRegistry
from app.graph.runtime import AgentGraphRuntime
from app.infrastructure.session_store import InMemorySessionStore
from app.mcp.client import LocalToolClient
from app.observability.futureagi import FutureAGIConfig, FutureAGISink
from app.observability.local import LocalJsonLogSink
from app.observability.service import ObservabilityService
from .realtime_fixtures import BlockingClassifier, session


@pytest.mark.asyncio
async def test_stream_emits_ack_before_slow_intent_classification() -> None:
    now = datetime(2026, 8, 29, tzinfo=UTC)
    store = InMemorySessionStore(ttl_seconds=60, clock=lambda: now)
    provider = MockProvider(ttl_seconds=60)
    await store.create(session("s-first-byte", now))
    provider._sessions.add("s-first-byte")
    classifier = BlockingClassifier()
    graph = AgentGraphRuntime(
        tool_client=LocalToolClient(),
        providers=ProviderRegistry([provider]),
        sessions=store,
        intent_classifier=classifier,
    )
    run_id = await store.begin_run("s-first-byte")
    assert run_id

    stream = graph.stream(
        user_id="u1", user_name="Tester", session_id="s-first-byte", message="今天天气怎么样", run_id=run_id
    )
    start = await asyncio.wait_for(anext(stream), timeout=0.2)
    filler = await asyncio.wait_for(anext(stream), timeout=0.2)
    assert start["event"] == "start"
    assert filler["event"] == "filler"
    assert filler["data"]["runId"] == run_id
    assert classifier.started.is_set() is False
    await stream.aclose()


@pytest.mark.asyncio
async def test_stream_close_before_processing_invalidates_run() -> None:
    now = datetime(2026, 8, 29, tzinfo=UTC)
    store = InMemorySessionStore(ttl_seconds=60, clock=lambda: now)
    provider = MockProvider(ttl_seconds=60)
    await store.create(session("s-early-close", now))
    provider._sessions.add("s-early-close")
    graph = AgentGraphRuntime(tool_client=LocalToolClient(), providers=ProviderRegistry([provider]), sessions=store)
    run_id = await store.begin_run("s-early-close")
    assert run_id
    stream = graph.stream(
        user_id="u1", user_name="Tester", session_id="s-early-close", message="hello", run_id=run_id
    )
    assert (await anext(stream))["event"] == "start"
    await stream.aclose()
    assert await store.is_interrupted("s-early-close", run_id) is True


@pytest.mark.asyncio
async def test_stream_error_emits_terminal_done_and_invalidates_run() -> None:
    now = datetime(2026, 8, 29, tzinfo=UTC)
    store = InMemorySessionStore(ttl_seconds=60, clock=lambda: now)
    provider = MockProvider(ttl_seconds=60)
    await store.create(session("s-stream-error", now))
    provider._sessions.add("s-stream-error")
    graph = AgentGraphRuntime(tool_client=LocalToolClient(), providers=ProviderRegistry([provider]), sessions=store)
    run_id = await store.begin_run("s-stream-error")
    assert run_id

    class BrokenGraph:
        async def astream(self, state, *, stream_mode: str):
            del state, stream_mode
            if False:
                yield {}
            raise RuntimeError("synthetic graph failure")

    graph._graph = BrokenGraph()
    events = [event async for event in graph.stream(
        user_id="u1",
        user_name="Tester",
        session_id="s-stream-error",
        message="hello",
        run_id=run_id,
    )]

    assert events[-2]["event"] == "error"
    assert events[-1]["event"] == "done"
    assert events[-1]["data"]["provider"] == "unknown"
    assert events[-1]["data"]["interrupted"] is False
    assert await store.is_interrupted("s-stream-error", run_id) is True


@pytest.mark.asyncio
async def test_stream_done_carries_realtime_latency_markers_and_trace_replay() -> None:
    now = datetime(2026, 8, 29, tzinfo=UTC)
    store = InMemorySessionStore(ttl_seconds=60, clock=lambda: now)
    provider = MockProvider(ttl_seconds=60)
    await store.create(session("s-latency", now))
    provider._sessions.add("s-latency")
    local = LocalJsonLogSink(max_events=100)
    observer = ObservabilityService(
        FutureAGISink(FutureAGIConfig(enabled=False), fallback=local),
        local_sink=local,
    )
    graph = AgentGraphRuntime(
        tool_client=LocalToolClient(),
        providers=ProviderRegistry([provider]),
        sessions=store,
        observer=observer,
    )
    run_id = await store.begin_run("s-latency")
    assert run_id

    events = [event async for event in graph.stream(
        user_id="u1",
        user_name="Tester",
        session_id="s-latency",
        message="hello",
        run_id=run_id,
    )]
    done = events[-1]["data"]
    assert done["firstEventLatencyMs"] is not None
    assert done["firstVisibleLatencyMs"] is not None
    replay = observer.trace_replay(done["traceId"], owner_id="u1")
    assert replay is not None
    assert replay.trace.first_event_latency_ms is not None
    assert replay.trace.first_visible_latency_ms is not None
    assert replay.trace.status == "ok"
    assert any(event.name == "agent.stream" for event in replay.events)
    assert {event.trace_id for event in replay.events} == {done["traceId"]}


@pytest.mark.asyncio
async def test_stream_interrupt_reports_cancellation_latency() -> None:
    now = datetime(2026, 8, 29, tzinfo=UTC)
    store = InMemorySessionStore(ttl_seconds=60, clock=lambda: now)
    provider = MockProvider(ttl_seconds=60)
    await store.create(session("s-cancel-latency", now))
    provider._sessions.add("s-cancel-latency")
    classifier = BlockingClassifier()
    graph = AgentGraphRuntime(
        tool_client=LocalToolClient(),
        providers=ProviderRegistry([provider]),
        sessions=store,
        intent_classifier=classifier,
    )
    run_id = await store.begin_run("s-cancel-latency")
    assert run_id
    stream = graph.stream(
        user_id="u1",
        user_name="Tester",
        session_id="s-cancel-latency",
        message="hello",
        run_id=run_id,
    )
    assert (await anext(stream))["event"] == "start"
    assert (await anext(stream))["event"] == "filler"
    pending = asyncio.create_task(anext(stream))
    await classifier.started.wait()
    await store.mark_interrupted("s-cancel-latency", run_id)
    interrupted = await pending
    done = await anext(stream)
    assert interrupted["event"] == "interrupted"
    assert done["event"] == "done"
    assert done["data"]["interrupted"] is True
    assert done["data"]["cancellationLatencyMs"] is not None
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
