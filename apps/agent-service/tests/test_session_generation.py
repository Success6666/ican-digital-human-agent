from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.application.session_service import SessionApplicationService
from app.avatar.registry import ProviderRegistry
from app.domain.models import AvatarCapabilities, AvatarSession, ProviderResult
from app.infrastructure.session_store import InMemorySessionStore


class ReusedIdProvider:
    name = "mock"

    def __init__(self, now: datetime) -> None:
        self.now = now
        self.close_started = asyncio.Event()
        self.release_close = asyncio.Event()
        self.close_calls: list[str] = []
        self.create_calls = 0

    async def capabilities(self) -> AvatarCapabilities:
        return AvatarCapabilities()

    async def create_session(self, user_id: str) -> AvatarSession:
        self.create_calls += 1
        return AvatarSession(
            session_id="reused-id",
            provider=self.name,
            user_id=user_id,
            capabilities=AvatarCapabilities(),
            created_at=self.now,
            expires_at=self.now + timedelta(seconds=30),
        )

    async def close_session(self, session_id: str) -> ProviderResult:
        self.close_calls.append(session_id)
        self.close_started.set()
        await self.release_close.wait()
        return ProviderResult(provider=self.name, status="closed")

    async def send_text(self, session_id: str, text: str, *, mode: str = "text", run_id: str | None = None) -> ProviderResult:
        return ProviderResult(provider=self.name, text=text)

    async def interrupt(self, session_id: str, *, run_id: str | None = None) -> ProviderResult:
        return ProviderResult(provider=self.name, status="interrupted")

    async def health(self):
        return None


class FlakyCloseProvider(ReusedIdProvider):
    def __init__(self, now: datetime) -> None:
        super().__init__(now)
        self.failures_left = 1

    async def close_session(self, session_id: str) -> ProviderResult:
        self.close_calls.append(session_id)
        if self.failures_left:
            self.failures_left -= 1
            raise RuntimeError("temporary provider failure")
        return ProviderResult(provider=self.name, status="closed")


def _session(now: datetime) -> AvatarSession:
    return AvatarSession(
        session_id="reused-id",
        provider="mock",
        user_id="u1",
        capabilities=AvatarCapabilities(),
        created_at=now,
        expires_at=now + timedelta(seconds=1),
    )


@pytest.mark.asyncio
async def test_expired_cleanup_skips_old_generation_after_id_reuse() -> None:
    now = datetime(2026, 8, 30, tzinfo=UTC)
    clock = [now]
    provider = ReusedIdProvider(now)
    store = InMemorySessionStore(ttl_seconds=1, idle_timeout_seconds=1, clock=lambda: clock[0])
    service = SessionApplicationService(providers=ProviderRegistry([provider]), store=store)
    await store.create(_session(now))

    clock[0] = now + timedelta(seconds=2)
    assert await store.get("reused-id") is None
    # A replacement is admitted before the cleanup worker drains the old
    # pending snapshot.  The old provider runtime must not be closed.
    replacement = _session(clock[0]).model_copy(update={"expires_at": clock[0] + timedelta(seconds=30)})
    await store.create(replacement)
    assert await service.cleanup_expired() == 1
    assert provider.close_calls == []
    assert (await store.get("reused-id")) is not None


@pytest.mark.asyncio
async def test_same_id_create_waits_for_expired_close_claim() -> None:
    now = datetime(2026, 8, 30, tzinfo=UTC)
    clock = [now]
    provider = ReusedIdProvider(now)
    store = InMemorySessionStore(ttl_seconds=1, idle_timeout_seconds=1, clock=lambda: clock[0])
    service = SessionApplicationService(providers=ProviderRegistry([provider]), store=store)
    await store.create(_session(now))
    clock[0] = now + timedelta(seconds=2)
    assert await store.get("reused-id") is None

    cleanup = asyncio.create_task(service.cleanup_expired())
    await asyncio.wait_for(provider.close_started.wait(), timeout=1)
    replacement = asyncio.create_task(service.create(user_id="u1", provider_name="mock"))
    await asyncio.sleep(0)
    assert replacement.done() is False

    provider.release_close.set()
    assert await cleanup == 1
    created = await asyncio.wait_for(replacement, timeout=1)
    assert created.session_id == "reused-id"
    current = await store.get("reused-id")
    assert current is not None
    assert current.generation_id


@pytest.mark.asyncio
async def test_failed_provider_cleanup_is_requeued_and_retried() -> None:
    now = datetime(2026, 8, 30, tzinfo=UTC)
    clock = [now]
    provider = FlakyCloseProvider(now)
    store = InMemorySessionStore(ttl_seconds=1, idle_timeout_seconds=1, clock=lambda: clock[0])
    service = SessionApplicationService(providers=ProviderRegistry([provider]), store=store)
    await store.create(_session(now))

    clock[0] = now + timedelta(seconds=2)
    assert await store.get("reused-id") is None
    assert await service.cleanup_expired() == 1
    assert provider.close_calls == ["reused-id"]
    stats = await store.stats()
    assert stats["expired_cleanup_requeued_total"] == 1

    # The failed snapshot remains available to the next cleanup pass.
    assert await service.cleanup_expired() == 1
    assert provider.close_calls == ["reused-id", "reused-id"]
    assert await store.remove_expired() == []


@pytest.mark.asyncio
async def test_cancelled_provider_cleanup_requeues_and_releases_generation_lock() -> None:
    now = datetime(2026, 8, 30, tzinfo=UTC)
    clock = [now]
    provider = ReusedIdProvider(now)
    store = InMemorySessionStore(ttl_seconds=1, idle_timeout_seconds=1, clock=lambda: clock[0])
    service = SessionApplicationService(providers=ProviderRegistry([provider]), store=store)
    await store.create(_session(now))

    clock[0] = now + timedelta(seconds=2)
    assert await store.get("reused-id") is None
    cleanup = asyncio.create_task(service.cleanup_expired())
    await asyncio.wait_for(provider.close_started.wait(), timeout=1)
    cleanup.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cleanup

    # Cancellation must not strand the per-id claim or lose the snapshot.
    replacement = asyncio.create_task(service.create(user_id="u1", provider_name="mock"))
    created = await asyncio.wait_for(replacement, timeout=1)
    assert created.session_id == "reused-id"
    assert await service.cleanup_expired() == 1
    assert await store.remove_expired() == []
    stats = await store.stats()
    assert stats["expired_cleanup_requeued_total"] == 1


@pytest.mark.asyncio
async def test_expired_requeue_is_bounded_and_deduplicated() -> None:
    now = datetime(2026, 8, 30, tzinfo=UTC)
    store = InMemorySessionStore(
        ttl_seconds=1,
        idle_timeout_seconds=1,
        max_sessions=1,
        cleanup_batch_size=1,
        clock=lambda: now,
    )
    record = await store.create(_session(now))
    del record
    expired = await store.remove_expired(now=now + timedelta(seconds=2))
    assert len(expired) == 1

    assert await store.requeue_expired(expired[0]) is True
    assert await store.requeue_expired(expired[0]) is False
    assert len(await store.remove_expired()) == 1
    stats = await store.stats()
    assert stats["expired_cleanup_duplicate_total"] == 1

    # The queue remains bounded even when many distinct failed snapshots are
    # offered by a cleanup worker under pressure.
    store._expired_pending_limit = 1
    second = expired[0].model_copy(deep=True)
    second.generation_id = "other-generation"
    assert await store.requeue_expired(second) is True
    third = expired[0].model_copy(deep=True)
    third.generation_id = "third-generation"
    assert await store.requeue_expired(third) is False
    stats = await store.stats()
    assert stats["expired_cleanup_dropped_total"] == 1


@pytest.mark.asyncio
async def test_slow_close_holds_generation_while_clock_advances() -> None:
    now = datetime(2026, 8, 30, tzinfo=UTC)
    clock = [now]
    provider = ReusedIdProvider(now)
    store = InMemorySessionStore(ttl_seconds=1, idle_timeout_seconds=1, clock=lambda: clock[0])
    service = SessionApplicationService(providers=ProviderRegistry([provider]), store=store)
    await store.create(_session(now))

    closing = asyncio.create_task(service.close(user_id="u1", session_id="reused-id"))
    await asyncio.wait_for(provider.close_started.wait(), timeout=1)
    clock[0] = now + timedelta(seconds=30)

    # TTL checks must not detach or clear the close-owned generation.
    current = await store.get("reused-id")
    assert current is not None
    assert current.session.status.value == "interrupted"
    assert await store.begin_run("reused-id") is None
    assert await store.is_interrupted("reused-id") is True
    marked = await store.mark_interrupted("reused-id")
    assert marked is not None
    assert await store.remove_expired() == []

    replacement = asyncio.create_task(service.create(user_id="u1", provider_name="mock"))
    await asyncio.sleep(0)
    assert replacement.done() is False

    provider.release_close.set()
    closed = await asyncio.wait_for(closing, timeout=1)
    assert closed is not None
    created = await asyncio.wait_for(replacement, timeout=1)
    assert created.session_id == "reused-id"


@pytest.mark.asyncio
async def test_same_provider_create_waits_before_remote_create_during_slow_close() -> None:
    """A reused provider id must not create a runtime beside an old close."""

    now = datetime(2026, 8, 30, tzinfo=UTC)
    provider = ReusedIdProvider(now)
    store = InMemorySessionStore(
        ttl_seconds=60,
        idle_timeout_seconds=60,
        clock=lambda: now,
    )
    service = SessionApplicationService(providers=ProviderRegistry([provider]), store=store)
    await store.create(
        _session(now).model_copy(update={"expires_at": now + timedelta(seconds=120)})
    )

    closing = asyncio.create_task(service.close(user_id="u1", session_id="reused-id"))
    await asyncio.wait_for(provider.close_started.wait(), timeout=1)

    replacement = asyncio.create_task(service.create(user_id="u1", provider_name="mock"))
    await asyncio.sleep(0)
    # Without provider lifecycle serialization, create_session would already
    # have allocated a remote runtime and only then block in store.create.
    assert provider.create_calls == 0
    assert replacement.done() is False

    provider.release_close.set()
    assert await asyncio.wait_for(closing, timeout=1) is not None
    created = await asyncio.wait_for(replacement, timeout=1)
    assert created.session_id == "reused-id"
    assert provider.create_calls == 1
