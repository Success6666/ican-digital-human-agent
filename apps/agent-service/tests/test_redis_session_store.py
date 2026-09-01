from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from app.domain.models import AvatarCapabilities, AvatarSession
from app.infrastructure.redis_session_store import RedisSessionStore


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("TEST_REDIS_URL"), reason="requires an explicit Redis test endpoint")
async def test_redis_store_shares_generation_state_between_instances() -> None:
    url = os.environ["TEST_REDIS_URL"]
    first = RedisSessionStore(redis_url=url, key_prefix="test:v034", ttl_seconds=60, idle_timeout_seconds=60, max_sessions=8, cleanup_batch_size=4)
    second = RedisSessionStore(redis_url=url, key_prefix="test:v034", ttl_seconds=60, idle_timeout_seconds=60, max_sessions=8, cleanup_batch_size=4)
    client = await first._client()
    assert client is not None
    await client.delete(first._state_key)
    now = datetime.now(UTC)
    await first.create(AvatarSession(session_id="shared", provider="mock", user_id="u1", capabilities=AvatarCapabilities(), created_at=now, expires_at=now + timedelta(seconds=60)))
    run_id = await second.begin_run("shared")
    assert run_id
    await first.mark_interrupted("shared", run_id)
    assert await second.is_interrupted("shared", run_id)
    await first.close_redis()
    await second.close_redis()
