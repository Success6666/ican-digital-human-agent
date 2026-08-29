"""Shared lifecycle helpers for the application-facing graph runtime."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from collections.abc import Awaitable, Callable
import time
from typing import Any

from ..agent.steering import RunInterrupted, RunToken, should_stop, wait_for_stop
from ..domain.ports import SessionStore


async def ensure_running(sessions: SessionStore, token: RunToken | None) -> None:
    """Abort work when the session has been interrupted or superseded."""
    if token is None:
        return
    if await should_stop(sessions, token):
        raise RunInterrupted("run interrupted or superseded")


async def run_with_steering(
    operation: Callable[[], Awaitable[Any]],
    *,
    sessions: SessionStore,
    token: RunToken | None,
    cancel_grace_seconds: float = 0.25,
) -> tuple[Any | None, bool]:
    """Run a cancellable external operation alongside the run-stop signal.

    Returning ``(None, True)`` means the run was stopped and the operation's
    result must not be published.  Provider adapters should allow
    ``CancelledError`` to reach their HTTP/WebSocket client so remote speech
    can stop at the transport boundary as well.
    """
    if token is None:
        # Compatibility callers without a run token cannot be steered. Avoid
        # creating a forever-polling stop task for that legacy path.
        return await operation(), False

    operation_task = asyncio.create_task(operation())
    stop_task = asyncio.create_task(wait_for_stop(sessions, token))
    try:
        done, _ = await asyncio.wait(
            {operation_task, stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        if operation_task in done:
            stop_task.cancel()
            await asyncio.gather(stop_task, return_exceptions=True)
            if await should_stop(sessions, token):
                # Consume a possible provider exception before suppressing the
                # stale result, otherwise asyncio reports an unhandled task.
                await asyncio.gather(operation_task, return_exceptions=True)
                return None, True
            return await operation_task, False

        await _cancel_operation(operation_task, cancel_grace_seconds)
        return None, True
    except asyncio.CancelledError:
        # A browser disconnect cancels the graph task itself. Both watcher and
        # external I/O must be cleaned here; otherwise a slow SDK can retain
        # session/provider references after the response is gone.
        await _cancel_operation(operation_task, cancel_grace_seconds)
        stop_task.cancel()
        await asyncio.gather(stop_task, return_exceptions=True)
        raise
    finally:
        if not stop_task.done():
            stop_task.cancel()
            await asyncio.gather(stop_task, return_exceptions=True)


async def _cancel_operation(task: asyncio.Task[Any], grace_seconds: float) -> None:
    """Cancel one external operation and consume any late completion."""
    if task.done():
        await asyncio.gather(task, return_exceptions=True)
        return
    task.cancel()
    cancelled_done, _ = await asyncio.wait(
        {task},
        timeout=max(0.01, grace_seconds),
    )
    if task in cancelled_done:
        await asyncio.gather(task, return_exceptions=True)
    else:
        # A non-cooperative adapter is isolated from the graph result. Keep a
        # callback so a late exception is consumed when its transport returns;
        # compliant adapters should finish during the grace window.
        task.add_done_callback(_consume_task)


def _consume_task(task: asyncio.Task[Any]) -> None:
    """Consume a detached provider task's eventual result or exception."""
    try:
        task.result()
    except BaseException:
        return


def safe_error(exc: Exception) -> str:
    """Return a bounded, single-line error suitable for an API event."""
    message = str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__
    return message[:300]


def agent_latency(*, started_at: float, digital_human_latency_ms: float | None) -> float:
    """Split total request time from the provider/avatar segment."""
    total_ms = max(0.0, (time.perf_counter() - started_at) * 1000)
    avatar_ms = max(0.0, digital_human_latency_ms or 0.0)
    return round(max(0.0, total_ms - avatar_ms), 2)


@asynccontextmanager
async def trace_scope(observer: Any | None, name: str, attributes: dict[str, Any]):
    """Use the optional observer without making it a runtime requirement."""
    if observer is None:
        yield
        return
    async with observer.start_trace(name, attributes=attributes):
        yield
