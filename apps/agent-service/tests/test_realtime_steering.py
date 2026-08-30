from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.agent.steering import RunToken
from app.avatar.adapters.mock import MockProvider
from app.avatar.errors import ProviderError
from app.avatar.registry import ProviderRegistry
from app.application.errors import ProviderUnavailableError, SessionOwnershipError
from app.application.session_service import SessionApplicationService
from app.domain.models import ProviderResult, SessionStatus
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
    # The close claim owns the session for the whole remote teardown window;
    # no new run may be created against a runtime that is being closed.
    assert await store.begin_run("s-close-race") is None

    provider.release.set()
    closed = await asyncio.wait_for(closing, timeout=1)
    assert closed is not None
    assert closed.status == SessionStatus.CLOSED
    assert provider.observed_interrupted == [True]
    assert await store.begin_run("s-close-race") is None


@pytest.mark.asyncio
async def test_close_claim_is_released_when_provider_teardown_fails() -> None:
    now = datetime(2026, 8, 29, tzinfo=UTC)
    store = InMemorySessionStore(ttl_seconds=60, clock=lambda: now)

    class FailingProvider(RecordingProvider):
        async def close_session(self, session_id: str):
            del session_id
            raise ProviderError("provider unavailable")

    provider = FailingProvider()
    service = SessionApplicationService(providers=ProviderRegistry([provider]), store=store)
    await store.create(session("s-close-fail", now))
    provider._sessions.add("s-close-fail")

    with pytest.raises(ProviderUnavailableError):
        await service.close(user_id="u1", session_id="s-close-fail")

    assert await store.is_closing("s-close-fail") is False
    resumed = await store.begin_run("s-close-fail")
    assert resumed


@pytest.mark.asyncio
async def test_close_claim_is_released_when_provider_is_missing() -> None:
    now = datetime(2026, 8, 29, tzinfo=UTC)
    store = InMemorySessionStore(ttl_seconds=60, clock=lambda: now)
    provider = MockProvider(ttl_seconds=60)
    service = SessionApplicationService(providers=ProviderRegistry([provider]), store=store)
    await store.create(session("s-close-missing", now).model_copy(update={"provider": "missing"}))

    with pytest.raises(ProviderUnavailableError):
        await service.close(user_id="u1", session_id="s-close-missing")

    assert await store.is_closing("s-close-missing") is False
    assert await store.begin_run("s-close-missing")


@pytest.mark.asyncio
async def test_concurrent_close_calls_share_one_provider_teardown() -> None:
    now = datetime(2026, 8, 29, tzinfo=UTC)
    store = InMemorySessionStore(ttl_seconds=60, clock=lambda: now)
    provider = SlowCloseProvider()
    provider.store = store
    service = SessionApplicationService(providers=ProviderRegistry([provider]), store=store)
    await store.create(session("s-close-once", now))
    provider._sessions.add("s-close-once")

    first = asyncio.create_task(service.close(user_id="u1", session_id="s-close-once"))
    await asyncio.wait_for(provider.started.wait(), timeout=1)
    second = asyncio.create_task(service.close(user_id="u1", session_id="s-close-once"))
    await asyncio.sleep(0)
    assert await store.begin_run("s-close-once") is None

    provider.release.set()
    first_result, second_result = await asyncio.gather(first, second)
    assert first_result and first_result.status == SessionStatus.CLOSED
    assert second_result and second_result.status == SessionStatus.CLOSED


@pytest.mark.asyncio
async def test_interrupt_waits_for_close_and_does_not_race_provider_teardown() -> None:
    now = datetime(2026, 8, 29, tzinfo=UTC)

    class RecordingSlowCloseProvider(SlowCloseProvider):
        def __init__(self) -> None:
            super().__init__()
            self.interrupt_calls: list[str | None] = []

        async def interrupt(self, session_id: str, *, run_id: str | None = None) -> ProviderResult:
            self.interrupt_calls.append(run_id)
            return await super().interrupt(session_id, run_id=run_id)

    store = InMemorySessionStore(ttl_seconds=60, clock=lambda: now)
    provider = RecordingSlowCloseProvider()
    provider.store = store
    service = SessionApplicationService(providers=ProviderRegistry([provider]), store=store)
    await store.create(session("s-close-interrupt-race", now))
    provider._sessions.add("s-close-interrupt-race")

    closing = asyncio.create_task(service.close(user_id="u1", session_id="s-close-interrupt-race"))
    await asyncio.wait_for(provider.started.wait(), timeout=1)
    interrupting = asyncio.create_task(
        service.interrupt(user_id="u1", session_id="s-close-interrupt-race")
    )
    await asyncio.sleep(0)
    assert provider.interrupt_calls == []

    provider.release.set()
    closed, interrupted = await asyncio.gather(closing, interrupting)
    assert closed is not None and closed.status == SessionStatus.CLOSED
    assert interrupted.status == SessionStatus.CLOSED
    assert provider.interrupt_calls == []


@pytest.mark.asyncio
async def test_explicit_close_wins_if_ttl_expires_during_teardown() -> None:
    now = datetime(2026, 8, 29, tzinfo=UTC)
    clock_value = [now]
    store = InMemorySessionStore(ttl_seconds=10, clock=lambda: clock_value[0])
    provider = SlowCloseProvider()
    provider.store = store
    service = SessionApplicationService(providers=ProviderRegistry([provider]), store=store)
    await store.create(session("s-close-ttl", now))
    provider._sessions.add("s-close-ttl")

    closing = asyncio.create_task(service.close(user_id="u1", session_id="s-close-ttl"))
    await asyncio.wait_for(provider.started.wait(), timeout=1)
    clock_value[0] = now + timedelta(seconds=10)
    provider.release.set()

    result = await asyncio.wait_for(closing, timeout=1)
    assert result is not None
    assert result.status == SessionStatus.CLOSED
    # A concurrent idempotent close sees the settled explicit-close result,
    # rather than treating the record as an expired 404.
    repeat = await service.close(user_id="u1", session_id="s-close-ttl")
    assert repeat is not None
    assert repeat.status == SessionStatus.CLOSED


@pytest.mark.asyncio
async def test_rebuilding_same_session_id_is_not_closed_by_old_teardown() -> None:
    now = datetime(2026, 8, 29, tzinfo=UTC)
    store = InMemorySessionStore(ttl_seconds=60, clock=lambda: now)
    provider = SlowCloseProvider()
    provider.store = store
    service = SessionApplicationService(providers=ProviderRegistry([provider]), store=store)
    await store.create(session("s-rebuild", now))
    provider._sessions.add("s-rebuild")

    closing = asyncio.create_task(service.close(user_id="u1", session_id="s-rebuild"))
    await asyncio.wait_for(provider.started.wait(), timeout=1)

    # A replacement waits for the old remote teardown to settle.  Allowing it
    # into the provider while close_session is in flight could close the new
    # generation when an SDK addresses runtimes by session id only.
    replacement = asyncio.create_task(store.create(session("s-rebuild", now)))
    await asyncio.sleep(0)
    assert replacement.done() is False

    provider.release.set()
    await asyncio.wait_for(closing, timeout=1)
    await asyncio.wait_for(replacement, timeout=1)
    replacement_run = await store.begin_run("s-rebuild")
    assert replacement_run

    current = await store.get("s-rebuild")
    assert current is not None
    assert current.session.status == SessionStatus.ACTIVE
    assert current.active_run_id == replacement_run


@pytest.mark.asyncio
async def test_stale_close_does_not_expose_rebuilt_session_to_other_user() -> None:
    now = datetime(2026, 8, 29, tzinfo=UTC)
    store = InMemorySessionStore(ttl_seconds=60, clock=lambda: now)
    provider = SlowCloseProvider()
    provider.store = store
    service = SessionApplicationService(providers=ProviderRegistry([provider]), store=store)
    await store.create(session("s-cross-user-close", now))
    provider._sessions.add("s-cross-user-close")

    closing = asyncio.create_task(service.close(user_id="u1", session_id="s-cross-user-close"))
    await asyncio.wait_for(provider.started.wait(), timeout=1)
    replacement = asyncio.create_task(
        store.create(session("s-cross-user-close", now).model_copy(update={"user_id": "u2"}))
    )
    await asyncio.sleep(0)
    assert replacement.done() is False
    provider.release.set()

    closed = await asyncio.wait_for(closing, timeout=1)
    assert closed is not None
    assert closed.status == SessionStatus.CLOSED
    await asyncio.wait_for(replacement, timeout=1)
    current = await store.get("s-cross-user-close")
    assert current is not None
    assert current.session.user_id == "u2"
    assert current.session.status == SessionStatus.ACTIVE


@pytest.mark.asyncio
async def test_stale_interrupt_does_not_expose_rebuilt_session_to_other_user() -> None:
    now = datetime(2026, 8, 29, tzinfo=UTC)

    class ReplacingStore(InMemorySessionStore):
        def __init__(self) -> None:
            super().__init__(ttl_seconds=60, clock=lambda: now)
            self.replaced = False

        async def mark_interrupted(self, session_id: str, run_id: str | None = None):
            updated = await super().mark_interrupted(session_id, run_id=run_id)
            if updated is not None and not self.replaced:
                self.replaced = True
                await self.create(
                    session(session_id, now).model_copy(update={"user_id": "u2"})
                )
                return await self.get(session_id)
            return updated

    store = ReplacingStore()
    provider = RecordingProvider()
    service = SessionApplicationService(providers=ProviderRegistry([provider]), store=store)
    await store.create(session("s-cross-user-interrupt", now))
    provider._sessions.add("s-cross-user-interrupt")
    run_id = await store.begin_run("s-cross-user-interrupt")
    assert run_id

    with pytest.raises(SessionOwnershipError):
        await service.interrupt(
            user_id="u1",
            session_id="s-cross-user-interrupt",
            run_id=run_id,
        )
    assert provider.interrupt_calls == []
    current = await store.get("s-cross-user-interrupt")
    assert current is not None
    assert current.session.user_id == "u2"
    assert current.session.status == SessionStatus.ACTIVE


@pytest.mark.asyncio
async def test_interrupt_resolves_provider_from_current_session_generation() -> None:
    now = datetime(2026, 8, 29, tzinfo=UTC)

    class ReplacingStore(InMemorySessionStore):
        def __init__(self) -> None:
            super().__init__(ttl_seconds=60, clock=lambda: now)
            self.replaced = False

        async def mark_interrupted(self, session_id: str, run_id: str | None = None):
            updated = await super().mark_interrupted(session_id, run_id=run_id)
            if updated is not None and not self.replaced:
                self.replaced = True
                await self.create(
                    session(session_id, now).model_copy(
                        update={"provider": "replacement"}
                    )
                )
                return await self.get(session_id)
            return updated

    store = ReplacingStore()
    previous = RecordingProvider()
    replacement = RecordingProvider()
    replacement.name = "replacement"
    service = SessionApplicationService(
        providers=ProviderRegistry([previous, replacement]),
        store=store,
    )
    await store.create(session("s-provider-generation", now))
    previous._sessions.add("s-provider-generation")
    replacement._sessions.add("s-provider-generation")
    run_id = await store.begin_run("s-provider-generation")
    assert run_id

    current = await service.interrupt(
        user_id="u1",
        session_id="s-provider-generation",
        run_id=run_id,
    )

    assert current.provider == "replacement"
    assert previous.interrupt_calls == []
    assert replacement.interrupt_calls == [run_id]


@pytest.mark.asyncio
async def test_stale_close_claim_cannot_abort_or_complete_newer_claim() -> None:
    now = datetime(2026, 8, 29, tzinfo=UTC)
    store = InMemorySessionStore(ttl_seconds=60, clock=lambda: now)
    await store.create(session("s-close-generation", now))

    first_claim = await store.claim_close_token("s-close-generation")
    assert first_claim

    # A replacement waits until the first provider close claim is released;
    # otherwise a slow SDK call could close the new remote generation.
    replacement_task = asyncio.create_task(store.create(session("s-close-generation", now)))
    await asyncio.sleep(0)
    assert replacement_task.done() is False
    await store.abort_close("s-close-generation", claim_token=first_claim)
    await asyncio.wait_for(replacement_task, timeout=1)

    # Reusing the id now starts a new generation, and a second close can claim
    # that replacement independently of the stale first token.
    second_claim = await store.claim_close_token("s-close-generation")
    assert second_claim and second_claim != first_claim

    stale_abort = await store.abort_close("s-close-generation", claim_token=first_claim)
    assert stale_abort is not None
    assert await store.is_closing("s-close-generation") is True
    current = await store.get("s-close-generation")
    assert current is not None
    assert current.session.status == SessionStatus.INTERRUPTED

    assert await store.complete_close("s-close-generation", claim_token=first_claim) is None
    assert await store.is_closing("s-close-generation") is True

    closed = await store.complete_close("s-close-generation", claim_token=second_claim)
    assert closed is not None
    assert closed.session.status == SessionStatus.CLOSED


@pytest.mark.asyncio
async def test_old_close_release_cannot_remove_reused_generation_mapping() -> None:
    now = datetime(2026, 8, 29, tzinfo=UTC)

    class InterleavedReleaseStore(InMemorySessionStore):
        def __init__(self) -> None:
            super().__init__(ttl_seconds=60, clock=lambda: now)
            self.pause_release = False
            self.release_started = asyncio.Event()
            self.resume_release = asyncio.Event()

        async def _release_generation_lock(self, session_id: str, lock: asyncio.Lock) -> None:
            if not self.pause_release:
                await super()._release_generation_lock(session_id, lock)
                return
            # Let a waiting claim acquire this exact lock before the old
            # close-release bookkeeping resumes.
            lock.release()
            self.release_started.set()
            await self.resume_release.wait()
            async with self._generation_lock_guard:
                users = max(0, self._generation_lock_users.get(session_id, 1) - 1)
                if users:
                    self._generation_lock_users[session_id] = users
                else:
                    self._generation_lock_users.pop(session_id, None)
                    if session_id not in self._expired_cleanup_claims:
                        self._generation_locks.pop(session_id, None)

    session_id = "s-close-mapping-reuse"
    store = InterleavedReleaseStore()
    await store.create(session(session_id, now))
    first_claim = await store.claim_close_token(session_id)
    assert first_claim
    reused_lock = store._close_generation_locks[session_id]
    store.pause_release = True

    aborting = asyncio.create_task(store.abort_close(session_id, claim_token=first_claim))
    await asyncio.wait_for(store.release_started.wait(), timeout=1)

    second_claim = await asyncio.wait_for(store.claim_close_token(session_id), timeout=1)
    assert second_claim and second_claim != first_claim
    assert store._close_generation_locks[session_id] is reused_lock

    store.resume_release.set()
    await asyncio.wait_for(aborting, timeout=1)

    # The old release must not delete the mapping owned by the newer claim.
    assert store._close_generation_locks[session_id] is reused_lock
    store.pause_release = False
    assert await store.complete_close(session_id, claim_token=second_claim)


@pytest.mark.asyncio
async def test_close_cancellation_during_finalize_releases_claim() -> None:
    now = datetime(2026, 8, 29, tzinfo=UTC)

    class BlockingCompleteStore(InMemorySessionStore):
        def __init__(self) -> None:
            super().__init__(ttl_seconds=60, clock=lambda: now)
            self.complete_started = asyncio.Event()

        async def complete_close(self, session_id: str, *, claim_token: str | None = None):
            self.complete_started.set()
            await asyncio.Event().wait()
            return await super().complete_close(session_id, claim_token=claim_token)

    store = BlockingCompleteStore()
    provider = MockProvider(ttl_seconds=60)
    service = SessionApplicationService(providers=ProviderRegistry([provider]), store=store)
    await store.create(session("s-close-cancel", now))
    provider._sessions.add("s-close-cancel")

    closing = asyncio.create_task(service.close(user_id="u1", session_id="s-close-cancel"))
    await asyncio.wait_for(store.complete_started.wait(), timeout=1)
    closing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await closing

    assert await store.is_closing("s-close-cancel") is False
    assert await store.begin_run("s-close-cancel")


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
    assert (await stream.__anext__())["event"] == "start"
    assert (await stream.__anext__())["event"] == "filler"
    interrupted_event = asyncio.create_task(stream.__anext__())
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
