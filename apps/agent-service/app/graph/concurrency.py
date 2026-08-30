"""Bounded async fan-out helpers for graph nodes."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar


T = TypeVar("T")
R = TypeVar("R")


async def bounded_map(
    items: Sequence[T],
    operation: Callable[[T], Awaitable[R]],
    *,
    limit: int,
) -> list[R]:
    """Apply an async operation with a fixed number of worker tasks.

    Results retain input order. The worker pool is explicitly cancelled and
    joined when its caller is cancelled, which keeps graph requests from
    retaining references to a disconnected stream.
    """
    if not items:
        return []
    worker_count = max(1, min(limit, len(items)))
    queue: asyncio.Queue[tuple[int, T]] = asyncio.Queue()
    for index, item in enumerate(items):
        queue.put_nowait((index, item))
    results: list[R | None] = [None] * len(items)
    failures: list[BaseException] = []

    async def worker() -> None:
        while True:
            try:
                index, item = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                results[index] = await operation(item)
            except asyncio.CancelledError:
                raise
            except BaseException as exc:  # preserve the first operation failure
                failures.append(exc)
            finally:
                queue.task_done()

    workers = [asyncio.create_task(worker(), name="agent-tool-worker") for _ in range(worker_count)]
    try:
        # Workers terminate when the queue is empty. Waiting on the worker
        # tasks themselves fails fast if an operation self-cancels; waiting
        # only on ``queue.join`` could deadlock with queued items remaining.
        await asyncio.gather(*workers)
    except asyncio.CancelledError:
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        raise
    finally:
        # ``queue.join`` normally drains all workers. This also handles an
        # unexpected worker exception without leaving siblings alive.
        for task in workers:
            if not task.done():
                task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

    if failures:
        raise failures[0]
    return [value for value in results]  # type: ignore[list-item]
