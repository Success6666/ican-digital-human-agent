"""Bounded serialization for remote provider session lifecycle calls."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass


@dataclass
class _ProviderLockEntry:
    lock: asyncio.Lock
    users: int = 0


class ProviderLifecycleRegistry:
    """Serialize create/close calls per provider without unbounded lock growth.

    Provider adapters commonly address runtimes by a session id.  A provider
    therefore must not receive a new ``create_session`` for an id while an old
    ``close_session`` is still in flight.  The registry deliberately covers
    only lifecycle operations; latency-sensitive interrupt calls use their
    existing session operation path and do not need this lock.

    Once the bounded table is full, new provider names share one overflow lock.
    Active overflow users temporarily keep subsequent new names on that lock,
    which prevents a name from switching between the fallback lock and a newly
    allocated per-name lock while an operation is still waiting.
    """

    def __init__(self, *, max_entries: int = 64) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self.max_entries = max_entries
        self._entries: dict[str, _ProviderLockEntry] = {}
        self._overflow_lock = asyncio.Lock()
        self._overflow_users = 0
        self._guard = asyncio.Lock()

    @asynccontextmanager
    async def hold(self, provider_name: str) -> AsyncIterator[None]:
        """Hold the lifecycle lock for one provider name."""

        if not isinstance(provider_name, str) or not provider_name:
            raise ValueError("provider_name must be a non-empty string")
        entry, overflow = await self._acquire(provider_name)
        lock = self._overflow_lock if overflow else entry.lock
        try:
            async with lock:
                yield
        finally:
            await self._release(provider_name, entry, overflow)

    async def _acquire(self, provider_name: str) -> tuple[_ProviderLockEntry | None, bool]:
        async with self._guard:
            entry = self._entries.get(provider_name)
            if entry is not None:
                entry.users += 1
                return entry, False
            if len(self._entries) >= self.max_entries or self._overflow_users:
                self._overflow_users += 1
                return None, True
            entry = _ProviderLockEntry(asyncio.Lock(), users=1)
            self._entries[provider_name] = entry
            return entry, False

    async def _release(
        self,
        provider_name: str,
        entry: _ProviderLockEntry | None,
        overflow: bool,
    ) -> None:
        async with self._guard:
            if overflow:
                self._overflow_users = max(0, self._overflow_users - 1)
                return
            if entry is None:
                return
            entry.users = max(0, entry.users - 1)
            if entry.users == 0 and self._entries.get(provider_name) is entry:
                self._entries.pop(provider_name, None)


__all__ = ["ProviderLifecycleRegistry"]
