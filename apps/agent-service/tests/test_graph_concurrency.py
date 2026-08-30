from __future__ import annotations

import asyncio

import pytest

from app.graph.concurrency import bounded_map


@pytest.mark.asyncio
async def test_bounded_map_limits_parallel_operations_and_preserves_order() -> None:
    active = 0
    peak = 0

    async def operation(value: int) -> int:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return value * 2

    result = await bounded_map(list(range(8)), operation, limit=2)

    assert result == [0, 2, 4, 6, 8, 10, 12, 14]
    assert peak == 2


@pytest.mark.asyncio
async def test_bounded_map_cancellation_reclaims_workers() -> None:
    started = 0
    cancelled = 0
    ready = asyncio.Event()

    async def operation(value: int) -> int:
        nonlocal started, cancelled
        del value
        started += 1
        if started == 2:
            ready.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled += 1
            raise

    task = asyncio.create_task(bounded_map([1, 2, 3, 4], operation, limit=2))
    await asyncio.wait_for(ready.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert cancelled == 2
    assert not [item for item in asyncio.all_tasks() if item.get_name() == "agent-tool-worker"]


@pytest.mark.asyncio
async def test_bounded_map_fails_fast_when_operation_self_cancels() -> None:
    started = asyncio.Event()

    async def operation(value: int) -> int:
        del value
        started.set()
        raise asyncio.CancelledError

    task = asyncio.create_task(bounded_map([1, 2], operation, limit=1))
    await asyncio.wait_for(started.wait(), timeout=1)
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=1)
    assert not [item for item in asyncio.all_tasks() if item.get_name() == "agent-tool-worker"]
