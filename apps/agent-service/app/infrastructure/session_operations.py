"""Bounded per-session serialization for provider lifecycle operations."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass


@dataclass
class _LockEntry:
    lock: asyncio.Lock
    users: int = 0


class SessionOperationRegistry:
    """Serialize close/interrupt calls without blocking unrelated sessions."""

    def __init__(self, *, max_entries: int = 4096) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self.max_entries = max_entries
        self._entries: dict[str, _LockEntry] = {}
        self._overflow_lock = asyncio.Lock()
        self._guard = asyncio.Lock()

    @asynccontextmanager
    async def hold(self, session_id: str) -> AsyncIterator[None]:
        entry, overflow = await self._acquire(session_id)
        lock = self._overflow_lock if overflow else entry.lock
        try:
            async with lock:
                yield
        finally:
            if not overflow:
                await self._release(session_id, entry)

    async def _acquire(self, session_id: str) -> tuple[_LockEntry, bool]:
        async with self._guard:
            entry = self._entries.get(session_id)
            if entry is None:
                if len(self._entries) >= self.max_entries:
                    # Keep the registry bounded under an unusual burst of
                    # distinct ids; only overflow ids share this fallback.
                    return _LockEntry(self._overflow_lock), True
                entry = _LockEntry(asyncio.Lock())
                self._entries[session_id] = entry
            entry.users += 1
            return entry, False

    async def _release(self, session_id: str, entry: _LockEntry) -> None:
        async with self._guard:
            entry.users = max(0, entry.users - 1)
            if entry.users == 0 and self._entries.get(session_id) is entry:
                self._entries.pop(session_id, None)


__all__ = ["SessionOperationRegistry"]
