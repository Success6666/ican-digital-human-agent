from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from app.agent.steering import RunToken
from app.avatar.adapters.mock import MockProvider
from app.avatar.registry import ProviderRegistry
from app.application.session_service import SessionApplicationService
from app.domain.models import SessionStatus
from app.graph.runtime import AgentGraphRuntime
from app.graph.runtime_support import run_with_steering
from app.infrastructure.session_store import InMemorySessionStore
from app.mcp.client import LocalToolClient
from .realtime_fixtures import (
    BlockingClassifier,
    KnowledgeClassifier,
    RecordingProvider,
    SlowCloseProvider,
    SlowProvider,
    SlowRag,
    SlowToolClient,
    session,
)


@pytest.mark.asyncio
async def test_stale_run_interrupt_does_not_stop_newer_run() -> None:
    now = datetime(2026, 8, 29, tzinfo=UTC)
    store = InMemorySessionStore(ttl_seconds=60, clock=lambda: now)
    provider = RecordingProvider()
    service = SessionApplicationService(providers=ProviderRegistry([provider]), store=store)
    await store.create(session("s-race", now))
    provider._sessions.add("s-race")

    first = await service.begin_run(user_id="u1", session_id="s-race")
    second = await service.begin_run(user_id="u1", session_id="s-race")
    assert first and second and first != second

    current = await service.interrupt(user_id="u1", session_id="s-race", run_id=first)
    assert current.status == SessionStatus.ACTIVE
    assert provider.interrupt_calls == []

    current = await service.interrupt(user_id="u1", session_id="s-race", run_id=second)
    assert current.status == SessionStatus.INTERRUPTED
    assert provider.interrupt_calls == [second]


@pytest.mark.asyncio
async def test_close_invalidates_run_before_slow_provider_teardown() -> None:
    now = datetime(2026, 8, 29, tzinfo=UTC)
    store = InMemorySessionStore(ttl_seconds=60, clock=lambda: now)
    provider = SlowCloseProvider()
    provider.store = store
    service = SessionApplicationService(providers=ProviderRegistry([provider]), store=store)
    await store.create(session("s-close-race", now))
    provider._sessions.add("s-close-race")
    run_id = await store.begin_run("s-close-race")
    assert run_id
    provider.run_id = run_id

    closing = asyncio.create_task(service.close(user_id="u1", session_id="s-close-race"))
    await asyncio.wait_for(provider.started.wait(), timeout=1)
    assert await store.is_interrupted("s-close-race", run_id) is True
    newer = await store.begin_run("s-close-race")
    assert newer and newer != run_id
    assert await store.is_interrupted("s-close-race", newer) is False

    provider.release.set()
    closed = await asyncio.wait_for(closing, timeout=1)
    assert closed is not None
    assert closed.status == SessionStatus.CLOSED
    assert provider.observed_interrupted == [True]
    assert await store.begin_run("s-close-race") is None


@pytest.mark.asyncio
async def test_superseding_run_cancels_inflight_provider_operation() -> None:
    now = datetime(2026, 8, 29, tzinfo=UTC)
    store = InMemorySessionStore(ttl_seconds=60, clock=lambda: now)
    provider = SlowProvider()
    await store.create(session("s-provider", now))
    provider._sessions.add("s-provider")
    graph = AgentGraphRuntime(
        tool_client=LocalToolClient(),
        providers=ProviderRegistry([provider]),
        sessions=store,
        provider_cancel_grace_seconds=0.1,
    )
    first = await store.begin_run("s-provider")
    assert first
    old_run = asyncio.create_task(
        graph.invoke(
            user_id="u1", user_name="Tester", session_id="s-provider", message="hello", run_id=first
        )
    )
    await asyncio.wait_for(provider.started.wait(), timeout=1)
    second = await store.begin_run("s-provider")
    assert second and second != first

    result = await asyncio.wait_for(old_run, timeout=1)
    assert result.interrupted is True
    assert result.provider == "unknown"
    assert provider.cancelled.is_set()


@pytest.mark.asyncio
async def test_superseding_run_cancels_slow_classifier() -> None:
    now = datetime(2026, 8, 29, tzinfo=UTC)
    store = InMemorySessionStore(ttl_seconds=60, clock=lambda: now)
    provider = MockProvider(ttl_seconds=60)
    await store.create(session("s-classifier", now))
    provider._sessions.add("s-classifier")
    classifier = BlockingClassifier()
    graph = AgentGraphRuntime(
        tool_client=LocalToolClient(),
        providers=ProviderRegistry([provider]),
        sessions=store,
        intent_classifier=classifier,
        provider_cancel_grace_seconds=0.1,
    )
    first = await store.begin_run("s-classifier")
    assert first
    stream = graph.stream(
        user_id="u1", user_name="Tester", session_id="s-classifier", message="今天天气怎么样", run_id=first
    )
    assert (await anext(stream))["event"] == "start"
    assert (await anext(stream))["event"] == "filler"
    interrupted_event = asyncio.create_task(anext(stream))
    await asyncio.wait_for(classifier.started.wait(), timeout=1)

    second = await store.begin_run("s-classifier")
    assert second and second != first
    remaining = [await interrupted_event]
    remaining.extend([event async for event in stream])
    assert any(event["event"] == "interrupted" for event in remaining)
    assert classifier.cancelled.is_set()


@pytest.mark.asyncio
async def test_sync_superseding_run_returns_terminal_result() -> None:
    now = datetime(2026, 8, 29, tzinfo=UTC)
    store = InMemorySessionStore(ttl_seconds=60, clock=lambda: now)
    provider = MockProvider(ttl_seconds=60)
    await store.create(session("s-sync-race", now))
    provider._sessions.add("s-sync-race")
    classifier = BlockingClassifier()
    graph = AgentGraphRuntime(
        tool_client=LocalToolClient(),
        providers=ProviderRegistry([provider]),
        sessions=store,
        intent_classifier=classifier,
        provider_cancel_grace_seconds=0.1,
    )
    first = await store.begin_run("s-sync-race")
    assert first
    old_run = asyncio.create_task(
        graph.invoke(
            user_id="u1", user_name="Tester", session_id="s-sync-race", message="今天天气怎么样", run_id=first
        )
    )
    await asyncio.wait_for(classifier.started.wait(), timeout=1)
    second = await store.begin_run("s-sync-race")
    assert second and second != first

    result = await asyncio.wait_for(old_run, timeout=1)
    assert result.interrupted is True
    assert result.provider == "unknown"
    assert result.run_id == first
    assert result.agent_response is not None
    assert classifier.cancelled.is_set()


@pytest.mark.asyncio
async def test_superseding_run_cancels_inflight_rag_search() -> None:
    now = datetime(2026, 8, 29, tzinfo=UTC)
    store = InMemorySessionStore(ttl_seconds=60, clock=lambda: now)
    provider = MockProvider(ttl_seconds=60)
    rag = SlowRag()
    await store.create(session("s-rag", now))
    provider._sessions.add("s-rag")
    graph = AgentGraphRuntime(
        tool_client=LocalToolClient(),
        providers=ProviderRegistry([provider]),
        sessions=store,
        rag_service=rag,
        intent_classifier=KnowledgeClassifier(),
        provider_cancel_grace_seconds=0.1,
    )
    first = await store.begin_run("s-rag")
    assert first
    old_run = asyncio.create_task(
        graph.invoke(user_id="u1", user_name="Tester", session_id="s-rag", message="查一下资料", run_id=first)
    )
    await asyncio.wait_for(rag.started.wait(), timeout=1)
    second = await store.begin_run("s-rag")
    assert second and second != first

    result = await asyncio.wait_for(old_run, timeout=1)
    assert result.interrupted is True
    assert rag.cancelled.is_set()


@pytest.mark.asyncio
async def test_superseding_run_cancels_inflight_mcp_call() -> None:
    now = datetime(2026, 8, 29, tzinfo=UTC)
    store = InMemorySessionStore(ttl_seconds=60, clock=lambda: now)
    provider = MockProvider(ttl_seconds=60)
    tools = SlowToolClient()
    await store.create(session("s-mcp", now))
    provider._sessions.add("s-mcp")
    graph = AgentGraphRuntime(
        tool_client=tools,
        providers=ProviderRegistry([provider]),
        sessions=store,
        provider_cancel_grace_seconds=0.1,
    )
    first = await store.begin_run("s-mcp")
    assert first
    old_run = asyncio.create_task(
        graph.invoke(user_id="u1", user_name="Tester", session_id="s-mcp", message="hello", run_id=first)
    )
    await asyncio.wait_for(tools.started.wait(), timeout=1)
    second = await store.begin_run("s-mcp")
    assert second and second != first

    result = await asyncio.wait_for(old_run, timeout=1)
    assert result.interrupted is True
    assert tools.cancelled > 0


@pytest.mark.asyncio
async def test_caller_cancellation_cleans_external_operation() -> None:
    now = datetime(2026, 8, 29, tzinfo=UTC)
    store = InMemorySessionStore(ttl_seconds=60, clock=lambda: now)
    await store.create(session("s-disconnect", now))
    run_id = await store.begin_run("s-disconnect")
    assert run_id
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def operation() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    task = asyncio.create_task(
        run_with_steering(
            operation,
            sessions=store,
            token=RunToken(session_id="s-disconnect", run_id=run_id),
            cancel_grace_seconds=0.1,
        )
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()
