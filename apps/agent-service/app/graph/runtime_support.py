"""Shared lifecycle helpers for the application-facing graph runtime."""

from __future__ import annotations

from contextlib import asynccontextmanager
import time
from typing import Any

from ..agent.steering import RunInterrupted, RunToken, should_stop
from ..domain.ports import SessionStore


async def ensure_running(sessions: SessionStore, token: RunToken | None) -> None:
    """Abort work when the session has been interrupted or superseded."""
    if token is None:
        return
    if await should_stop(sessions, token):
        raise RunInterrupted("run interrupted or superseded")


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
