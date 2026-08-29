"""Run-token and cooperative steering helpers for LangGraph execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4


class RunInterrupted(RuntimeError):
    """Raised by an optional caller when a run should stop immediately."""


@dataclass(slots=True, frozen=True)
class RunToken:
    session_id: str
    run_id: str


async def open_run(store: Any, session_id: str) -> RunToken:
    """Issue a token through the store, with a compatibility fallback."""
    begin = getattr(store, "begin_run", None)
    run_id = await begin(session_id) if begin is not None else uuid4().hex
    if not run_id:
        raise RunInterrupted("session is not available")
    return RunToken(session_id=session_id, run_id=str(run_id))


async def should_stop(store: Any, token: RunToken | None) -> bool:
    """Check interruption/supersession without requiring a concrete store."""
    if token is None:
        return False
    checker = getattr(store, "is_interrupted", None)
    if checker is not None:
        return bool(await checker(token.session_id, token.run_id))
    record = await store.get(token.session_id)
    return record is None or bool(getattr(record, "interrupted", False))


async def ensure_running(store: Any, token: RunToken | None) -> None:
    if await should_stop(store, token):
        raise RunInterrupted("run interrupted or superseded")
