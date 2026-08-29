from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from app.avatar.adapters.mock import MockProvider
from app.avatar.registry import ProviderRegistry
from app.graph.runtime import AgentGraphRuntime
from app.infrastructure.session_store import InMemorySessionStore
from app.mcp.client import LocalToolClient
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
