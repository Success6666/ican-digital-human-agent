"""Small bounded-value and asyncio helpers for observability internals."""

from __future__ import annotations

import asyncio
import math
from typing import Any


def positive_int(raw: str | None, default: int) -> int:
    try:
        value = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def positive_float(raw: str | None, default: float) -> float:
    try:
        value = float(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) and value > 0 else default


def latency_value(value: Any) -> float | None:
    """Normalize a latency marker without allowing NaN or infinity through."""

    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed < 0:
        return None
    return round(parsed, 2)


def consume_task_result(task: asyncio.Task[Any]) -> None:
    """Consume a detached task result so late failures stay out of logs."""

    try:
        task.result()
    except BaseException:
        return


def cancel_task_threadsafe(task: asyncio.Task[Any], *, current_loop: asyncio.AbstractEventLoop) -> None:
    """Cancel a task from its owning loop, when that loop differs from current."""

    try:
        task_loop = task.get_loop()
    except RuntimeError:
        return
    if task_loop is current_loop or not task_loop.is_running():
        task.cancel()
        return
    task_loop.call_soon_threadsafe(task.cancel)


__all__ = [
    "cancel_task_threadsafe",
    "consume_task_result",
    "latency_value",
    "positive_float",
    "positive_int",
]
