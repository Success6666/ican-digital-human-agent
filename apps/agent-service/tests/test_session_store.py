from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.models import AvatarCapabilities, AvatarSession, SessionStatus
from app.application.session_service import SessionApplicationService
from app.avatar.registry import ProviderRegistry
from app.infrastructure.session_store import InMemorySessionStore


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
