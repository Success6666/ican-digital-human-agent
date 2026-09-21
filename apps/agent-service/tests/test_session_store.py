from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.application.errors import SessionCapacityExceededError
from app.application.session_service import SessionApplicationService
from app.avatar.registry import ProviderRegistry
from app.domain.models import AvatarCapabilities, AvatarSession, SessionStatus
from app.domain.ports import SessionCapacityError
from app.infrastructure.session_store import InMemorySessionStore


def _session(session_id: str, now: datetime, *, ttl: int = 30) -> AvatarSession:
    return AvatarSession(
        session_id=session_id,
        provider="mock",
        user_id="u1",
        capabilities=AvatarCapabilities(),
        created_at=now,
        expires_at=now + timedelta(seconds=ttl),
    )


@pytest.mark.asyncio
async def test_sliding_ttl_and_cleanup() -> None:
    now = datetime(2026, 8, 29, tzinfo=UTC)
    clock_value = [now]
    store = InMemorySessionStore(ttl_seconds=10, clock=lambda: clock_value[0])
    session = AvatarSession(
        session_id="s1",
        provider="mock",
        user_id="u1",
        capabilities=AvatarCapabilities(),
        created_at=now,
        expires_at=now + timedelta(seconds=10),
    )
    await store.create(session)
    clock_value[0] = now + timedelta(seconds=5)
    await store.touch("s1")
    clock_value[0] = now + timedelta(seconds=12)
    assert await store.get("s1") is not None
    clock_value[0] = now + timedelta(seconds=16)
    assert await store.get("s1") is None
    expired = await store.remove_expired()
    assert len(expired) == 1
    assert expired[0].session.status == SessionStatus.EXPIRED


@pytest.mark.asyncio
async def test_closed_session_is_reclaimed_after_ttl() -> None:
    now = datetime(2026, 8, 29, tzinfo=UTC)
    clock_value = [now]
    store = InMemorySessionStore(ttl_seconds=10, clock=lambda: clock_value[0])
    session = AvatarSession(
        session_id="closed-1",
        provider="mock",
        user_id="u1",
        capabilities=AvatarCapabilities(),
        created_at=now,
        expires_at=now + timedelta(seconds=10),
    )
    await store.create(session)
    await store.close(session.session_id)

    clock_value[0] = now + timedelta(seconds=9)
    assert await store.size() == 1
    clock_value[0] = now + timedelta(seconds=10)
    expired = await store.remove_expired()

    assert await store.size() == 0
    assert len(expired) == 1
    assert expired[0].session.status == SessionStatus.CLOSED


@pytest.mark.asyncio
async def test_cleanup_does_not_close_provider_twice_for_closed_session() -> None:
    class CountingProvider:
        name = "mock"

        def __init__(self) -> None:
            self.close_calls = 0

        async def close_session(self, session_id: str):
            self.close_calls += 1
            return None

    now = datetime(2026, 8, 29, tzinfo=UTC)
    clock_value = [now]
    provider = CountingProvider()
    store = InMemorySessionStore(ttl_seconds=10, clock=lambda: clock_value[0])
    service = SessionApplicationService(providers=ProviderRegistry([provider]), store=store)
    session = AvatarSession(
        session_id="closed-2",
        provider="mock",
        user_id="u1",
        capabilities=AvatarCapabilities(),
        created_at=now,
        expires_at=now + timedelta(seconds=10),
    )
    await store.create(session)
    await store.close(session.session_id)
    clock_value[0] = now + timedelta(seconds=10)

    assert await service.cleanup_expired() == 1
    assert provider.close_calls == 0


@pytest.mark.asyncio
async def test_capacity_reclaims_closed_before_rejecting() -> None:
    now = datetime(2026, 8, 30, tzinfo=UTC)
    store = InMemorySessionStore(max_sessions=1, cleanup_batch_size=1, clock=lambda: now)
    await store.create(_session("s1", now))
    with pytest.raises(SessionCapacityError):
        await store.create(_session("s2", now))

    await store.close("s1")
    await store.create(_session("s2", now))
    stats = await store.stats()
    assert stats["active_sessions"] == 1
    assert stats["capacity_rejected_total"] == 1
    assert stats["closed_reclaimed_total"] == 1


@pytest.mark.asyncio
async def test_heartbeat_renews_lease_and_rejects_stale_run() -> None:
    now = datetime(2026, 8, 30, tzinfo=UTC)
    clock_value = [now]
    store = InMemorySessionStore(ttl_seconds=10, idle_timeout_seconds=10, clock=lambda: clock_value[0])
    await store.create(_session("s1", now, ttl=60))
    run_id = await store.begin_run("s1", run_id="run-1")
    assert run_id == "run-1"

    clock_value[0] = now + timedelta(seconds=8)
    assert await store.heartbeat("s1", "run-1") is True
    assert await store.heartbeat("s1", "old-run") is False
    clock_value[0] = now + timedelta(seconds=19)
    assert await store.get("s1") is None
    stats = await store.stats()
    assert stats["heartbeat_total"] == 1
    assert stats["heartbeat_rejected_total"] == 1
    assert stats["stale_touch_rejected_total"] == 1


@pytest.mark.asyncio
async def test_expired_cleanup_honors_batch_limit() -> None:
    now = datetime(2026, 8, 30, tzinfo=UTC)
    store = InMemorySessionStore(
        ttl_seconds=5,
        idle_timeout_seconds=5,
        cleanup_batch_size=2,
        clock=lambda: now,
    )
    for index in range(3):
        await store.create(_session(f"s{index}", now, ttl=1))

    assert len(await store.remove_expired(now=now + timedelta(seconds=2))) == 2
    assert await store.size() == 1
    assert len(await store.remove_expired(now=now + timedelta(seconds=2))) == 1
    assert await store.size() == 0


@pytest.mark.asyncio
async def test_expired_session_releases_capacity_before_cleanup() -> None:
    now = datetime(2026, 8, 30, tzinfo=UTC)
    clock_value = [now]
    store = InMemorySessionStore(
        max_sessions=1,
        cleanup_batch_size=1,
        ttl_seconds=5,
        idle_timeout_seconds=5,
        clock=lambda: clock_value[0],
    )
    await store.create(_session("expired", now, ttl=1))

    clock_value[0] = now + timedelta(seconds=2)
    assert await store.get("expired") is None
    await store.create(_session("fresh", clock_value[0], ttl=5))

    assert await store.size() == 1
    pending = await store.remove_expired()
    assert [record.session.session_id for record in pending] == ["expired"]


@pytest.mark.asyncio
async def test_capacity_error_is_translated_and_remote_session_is_closed() -> None:
    class Provider:
        name = "mock"

        def __init__(self) -> None:
            self.index = 0
            self.close_calls = 0

        async def create_session(self, user_id: str) -> AvatarSession:
            self.index += 1
            return _session(f"p{self.index}", now).model_copy(update={"user_id": user_id})

        async def close_session(self, session_id: str) -> None:
            del session_id
            self.close_calls += 1

    now = datetime(2026, 8, 30, tzinfo=UTC)
    provider = Provider()
    service = SessionApplicationService(
        providers=ProviderRegistry([provider]),
        store=InMemorySessionStore(max_sessions=1, clock=lambda: now),
    )
    await service.create(user_id="u1", provider_name="mock")
    with pytest.raises(SessionCapacityExceededError) as error:
        await service.create(user_id="u1", provider_name="mock")
    assert error.value.status_code == 429
    assert provider.close_calls == 1


@pytest.mark.asyncio
async def test_cleanup_outbox_recovers_expired_snapshot_after_store_restart(tmp_path) -> None:
    now = datetime(2026, 8, 30, tzinfo=UTC)
    clock_value = [now]
    outbox = tmp_path / "cleanup.jsonl"
    store = InMemorySessionStore(
        ttl_seconds=5,
        idle_timeout_seconds=5,
        clock=lambda: clock_value[0],
        cleanup_outbox_path=str(outbox),
    )
    await store.create(_session("restart-expired", now, ttl=1))
    clock_value[0] = now + timedelta(seconds=2)
    assert await store.get("restart-expired") is None
    assert outbox.exists()

    restarted = InMemorySessionStore(
        ttl_seconds=5,
        idle_timeout_seconds=5,
        clock=lambda: clock_value[0],
        cleanup_outbox_path=str(outbox),
    )
    recovered = await restarted.remove_expired()
    assert [record.session.session_id for record in recovered] == ["restart-expired"]
    assert outbox.read_text(encoding="utf-8") == ""


@pytest.mark.asyncio
async def test_cleanup_outbox_skips_corrupt_lines_and_deduplicates(tmp_path) -> None:
    now = datetime(2026, 8, 30, tzinfo=UTC)
    record = _session("recoverable", now, ttl=1)
    from app.domain.models import SessionRecord

    payload = SessionRecord(
        session=record.model_copy(update={"status": SessionStatus.EXPIRED}),
        last_activity=now,
        generation_id="generation-1",
    ).model_dump(mode="json")
    outbox = tmp_path / "cleanup.jsonl"
    outbox.write_text(
        "not-json\n{}\n" + json.dumps(payload, ensure_ascii=False) + "\n" + json.dumps(payload) + "\n",
        encoding="utf-8",
    )
    store = InMemorySessionStore(
        ttl_seconds=5,
        idle_timeout_seconds=5,
        clock=lambda: now,
        cleanup_outbox_path=str(outbox),
    )
    recovered = await store.remove_expired()
    assert len(recovered) == 1
    assert recovered[0].generation_id == "generation-1"


@pytest.mark.asyncio
async def test_cleanup_outbox_persists_failed_teardown_requeue(tmp_path) -> None:
    now = datetime(2026, 8, 30, tzinfo=UTC)
    outbox = tmp_path / "cleanup.jsonl"
    store = InMemorySessionStore(
        ttl_seconds=5,
        idle_timeout_seconds=5,
        clock=lambda: now,
        cleanup_outbox_path=str(outbox),
    )
    await store.create(_session("failed-teardown", now, ttl=1))
    expired = await store.remove_expired(now=now + timedelta(seconds=2))
    assert len(expired) == 1
    assert await store.requeue_expired(expired[0]) is True

    restarted = InMemorySessionStore(
        ttl_seconds=5,
        idle_timeout_seconds=5,
        clock=lambda: now,
        cleanup_outbox_path=str(outbox),
    )
    recovered = await restarted.remove_expired()
    assert [record.session.session_id for record in recovered] == ["failed-teardown"]
