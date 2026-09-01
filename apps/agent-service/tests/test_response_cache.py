import asyncio

import pytest

from app.domain.models import ChatResult
from app.infrastructure.response_cache import ResponseCache


@pytest.mark.asyncio
async def test_singleflight_calls_compute_once_and_reuses_result():
    cache = ResponseCache(redis_url="redis://127.0.0.1:6399/0", ttl_seconds=30)
    calls = 0

    async def compute():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.02)
        return ChatResult(reply="ok", trace_id="t", session_id="s", run_id="r", provider="mock")

    results = await asyncio.gather(*(cache.get_or_compute("k", compute) for _ in range(8)))
    assert calls == 1
    assert all(item[0].reply == "ok" for item in results)
    assert any(item[1] for item in results)


@pytest.mark.asyncio
async def test_local_cache_hit_slides_ttl():
    cache = ResponseCache(redis_url="redis://127.0.0.1:6399/0", ttl_seconds=30)
    result = ChatResult(reply="ok", trace_id="t", session_id="s", provider="mock")
    assert await cache.set("k", result)
    first = cache._local["k"][0]
    assert await cache.get("k") is not None
    assert cache._local["k"][0] >= first
