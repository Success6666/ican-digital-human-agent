"""Bounded sink transport helpers for the observability facade."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

from .models import TelemetryEvent
from .utils import cancel_task_threadsafe, consume_task_result


def emit_sync(service: Any, event: TelemetryEvent) -> None:
    """Emit from synchronous span hooks without blocking an active loop."""

    event = service._stamp(event)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        emit_method = getattr(service.sink, "emit_sync", None)
        if callable(emit_method):
            service._mirror_local_if_needed(event)
            try:
                emit_method(event)
            except Exception:
                return
            return
        service._mirror_local_if_needed(event)
        try:
            asyncio.run(emit_async(service, event))
        except Exception:
            return
    else:
        schedule_async(service, loop, event)


async def emit_async(service: Any, event: TelemetryEvent, *, mirror: bool = True) -> None:
    """Run exporter I/O asynchronously and isolate sink failures."""

    event = service._stamp(event)
    if mirror:
        service._mirror_local_if_needed(event)
    try:
        emit_method = getattr(service.sink, "emit", None)
        if not callable(emit_method):
            emit_sync_method = getattr(service.sink, "emit_sync", None)
            if not callable(emit_sync_method):
                return
            await asyncio.to_thread(emit_sync_method, event)
            return
        result = emit_method(event)
        if inspect.isawaitable(result):
            await result
    except Exception:
        return


def schedule_async(service: Any, loop: asyncio.AbstractEventLoop, event: TelemetryEvent) -> None:
    """Queue one export while retaining a bounded local replay copy."""

    service._record_local(event)
    prune_pending(service)
    with service._pending_lock:
        if len(service._pending_tasks) >= service.max_pending_tasks:
            service._dropped_events += 1
            overflow = True
        else:
            coroutine = emit_async(service, event, mirror=False)
            try:
                task = loop.create_task(coroutine)
            except RuntimeError:
                coroutine.close()
                service._dropped_events += 1
                overflow = True
            else:
                service._pending_tasks.add(task)
                overflow = False
    if overflow:
        return
    task.add_done_callback(lambda completed: pending_done(service, completed))


def pending_task_count(service: Any) -> int:
    prune_pending(service)
    with service._pending_lock:
        return len(service._pending_tasks)


def pending_done(service: Any, task: asyncio.Task[Any]) -> None:
    with service._pending_lock:
        service._pending_tasks.discard(task)
    consume_task_result(task)


def prune_pending(service: Any) -> None:
    with service._pending_lock:
        done = [task for task in service._pending_tasks if task.done()]
        for task in done:
            service._pending_tasks.discard(task)
    for task in done:
        consume_task_result(task)


async def flush_pending(service: Any) -> None:
    """Drain current-loop exports within the configured shutdown budget."""

    loop = asyncio.get_running_loop()
    prune_pending(service)
    with service._pending_lock:
        current = [task for task in service._pending_tasks if task.get_loop() is loop]
        foreign = [task for task in service._pending_tasks if task.get_loop() is not loop]
    for task in foreign:
        cancel_task_threadsafe(task, current_loop=loop)
    discard_pending(service, foreign)
    if not current:
        return
    _, pending = await asyncio.wait(current, timeout=service.pending_flush_timeout_seconds)
    if pending:
        for task in pending:
            task.cancel()
        # Do not wait forever for a non-cooperative exporter during shutdown.
        await asyncio.wait(pending, timeout=min(0.25, service.pending_flush_timeout_seconds))
        discard_pending(service, list(pending))
    prune_pending(service)


def discard_pending(service: Any, tasks: list[asyncio.Task[Any]]) -> None:
    if not tasks:
        return
    with service._pending_lock:
        for task in tasks:
            service._pending_tasks.discard(task)


__all__ = [
    "discard_pending",
    "emit_async",
    "emit_sync",
    "flush_pending",
    "pending_done",
    "pending_task_count",
    "prune_pending",
    "schedule_async",
]
