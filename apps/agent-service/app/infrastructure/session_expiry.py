"""Bounded expiry admission and provider-cleanup coordination."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import uuid4

from ..domain.models import AvatarSession, SessionRecord, SessionStatus
from ..domain.ports import SessionCapacityError
from .session_resources import resource_limit, utc


class SessionExpiryMixin:
    """Keep expiry queues and same-id generation locks out of the store core."""

    _items: dict[str, SessionRecord]
    _clock: Callable[[], datetime]
    _lock: asyncio.Lock
    _metrics: object
    _stop_events: dict[str, asyncio.Event]
    _close_events: dict[str, asyncio.Event]
    _close_claims: dict[str, str]
    _closing: set[str]
    _stop_requested_at: dict[tuple[str, str], float]
    max_sessions: int
    cleanup_batch_size: int
    idle_timeout_seconds: int

    def _init_expiry_lifecycle(self) -> None:
        self._expired_pending: deque[SessionRecord] = deque()
        self._expired_pending_keys: set[tuple[str, str]] = set()
        self._expired_pending_limit = min(
            4096, max(self.cleanup_batch_size * 4, self.max_sessions)
        )
        self._generation_locks: dict[str, asyncio.Lock] = {}
        self._generation_lock_users: dict[str, int] = {}
        self._generation_lock_guard = asyncio.Lock()
        self._expired_cleanup_claims: dict[str, str] = {}
        # Explicit provider close claims share the same per-id lease.  Keeping
        # the lock by session id lets the close mixin release it only after
        # provider I/O and claim finalization both settle.
        self._close_generation_locks: dict[str, asyncio.Lock] = {}

    async def create(self, session: AvatarSession) -> None:
        lock = await self._acquire_generation_lock(session.session_id)
        try:
            await self._create_locked(session)
        finally:
            await self._release_generation_lock(session.session_id, lock)

    async def _create_locked(self, session: AvatarSession) -> None:
        async with self._lock:
            existing = self._items.get(session.session_id)
            if (
                existing is not None
                and session.session_id not in self._closing
                and self._is_expired(existing, utc(self._clock()))
                and existing.session.status != SessionStatus.CLOSED
            ):
                if not self._detach_expired_locked(session.session_id, existing):
                    self._metrics.capacity_rejected_total += 1
                    raise SessionCapacityError("expired session cleanup backlog reached")
                existing = None
            if existing is None:
                self._reclaim_closed_locked(self.cleanup_batch_size)
                self._reclaim_expired_locked(self.cleanup_batch_size)
                if len(self._items) >= self.max_sessions:
                    self._metrics.capacity_rejected_total += 1
                    raise SessionCapacityError("session capacity reached")
            else:
                if session.session_id in self._closing:
                    self._metrics.close_superseded_total += 1
                self._metrics.replaced_total += 1
            self._replace_generation_locked(session)

    def _replace_generation_locked(self, session: AvatarSession) -> None:
        previous_stop = self._stop_events.pop(session.session_id, None)
        if previous_stop is not None:
            previous_stop.set()
        previous_close = self._close_events.pop(session.session_id, None)
        if previous_close is not None:
            previous_close.set()
        self._close_claims.pop(session.session_id, None)
        self._closing.discard(session.session_id)
        self._clear_stop_timestamps_locked(session.session_id)
        current = utc(self._clock())
        snapshot = session.model_copy(deep=True)
        snapshot.expires_at = min(
            utc(snapshot.expires_at),
            current + timedelta(seconds=self.idle_timeout_seconds),
        )
        self._items[session.session_id] = SessionRecord(
            session=snapshot,
            last_activity=current,
            generation_id=uuid4().hex,
        )
        self._stop_events[session.session_id] = asyncio.Event()
        self._metrics.created_total += 1

    async def claim_expired_cleanup(self, session_id: str, generation_id: str | None) -> bool:
        """Hold a per-id lease while the provider teardown is in flight."""
        lock = await self._acquire_generation_lock(session_id)
        token = self._generation_token(session_id, generation_id)
        claimed = False
        try:
            async with self._lock:
                current = self._items.get(session_id)
                if current is not None or session_id in self._expired_cleanup_claims:
                    self._forget_pending_key_locked((session_id, token))
                    self._metrics.expired_cleanup_skipped_replaced_total += 1
                    return False
                self._expired_cleanup_claims[session_id] = token
                claimed = True
                return True
        finally:
            if not claimed:
                await self._release_generation_lock(session_id, lock)

    async def finish_expired_cleanup(self, session_id: str, generation_id: str | None) -> None:
        lock = self._generation_locks.get(session_id)
        if lock is None:
            return
        token = self._generation_token(session_id, generation_id)
        async with self._lock:
            if self._expired_cleanup_claims.get(session_id) != token:
                return
            self._expired_cleanup_claims.pop(session_id, None)
        await self._release_generation_lock(session_id, lock)

    async def requeue_expired(self, record: SessionRecord) -> bool:
        """Requeue failed teardown without duplicate or unbounded growth."""
        key = self._pending_key(record)
        async with self._lock:
            current = self._items.get(record.session.session_id)
            if current is not None:
                self._forget_pending_key_locked(key)
                self._metrics.expired_cleanup_skipped_replaced_total += 1
                return False
            if key in self._expired_pending_keys:
                self._metrics.expired_cleanup_duplicate_total += 1
                return False
            if len(self._expired_pending) >= self._expired_pending_limit:
                self._metrics.expired_cleanup_dropped_total += 1
                return False
            snapshot = self._snapshot(record)
            assert snapshot is not None
            self._expired_pending.append(snapshot)
            self._expired_pending_keys.add(key)
            self._metrics.expired_cleanup_requeued_total += 1
            self._after_pending_change_locked()
            return True

    async def remove_expired(
        self,
        now: datetime | None = None,
        *,
        limit: int | None = None,
    ) -> list[SessionRecord]:
        current = utc(now or self._clock())
        batch = self.cleanup_batch_size if limit is None else resource_limit(limit, "limit", 10_000)
        async with self._lock:
            expired: list[SessionRecord] = []
            reclaimed = 0
            while self._expired_pending and reclaimed < batch:
                record = self._expired_pending.popleft()
                self._expired_pending_keys.discard(self._pending_key(record))
                expired.append(record)
                self._metrics.expired_reclaimed_total += 1
                reclaimed += 1
            for session_id, record in list(self._items.items()):
                if reclaimed >= batch:
                    break
                if session_id in self._closing:
                    continue
                if not self._is_expired(record, current):
                    continue
                was_closed = record.session.status == SessionStatus.CLOSED
                snapshot = self._detach_expired_locked(session_id, record, enqueue=False)
                if snapshot is None:
                    continue
                expired.append(snapshot)
                counter = "closed_reclaimed_total" if was_closed else "expired_reclaimed_total"
                setattr(self._metrics, counter, getattr(self._metrics, counter) + 1)
                reclaimed += 1
            self._after_pending_change_locked()
            return expired

    async def _acquire_generation_lock(self, session_id: str) -> asyncio.Lock:
        async with self._generation_lock_guard:
            lock = self._generation_locks.setdefault(session_id, asyncio.Lock())
            self._generation_lock_users[session_id] = self._generation_lock_users.get(session_id, 0) + 1
        try:
            await lock.acquire()
        except BaseException:
            async with self._generation_lock_guard:
                users = max(0, self._generation_lock_users.get(session_id, 1) - 1)
                if users:
                    self._generation_lock_users[session_id] = users
                else:
                    self._generation_lock_users.pop(session_id, None)
                    if session_id not in self._expired_cleanup_claims:
                        self._generation_locks.pop(session_id, None)
            raise
        return lock

    async def _release_generation_lock(self, session_id: str, lock: asyncio.Lock) -> None:
        lock.release()
        async with self._generation_lock_guard:
            users = max(0, self._generation_lock_users.get(session_id, 1) - 1)
            if users:
                self._generation_lock_users[session_id] = users
            else:
                self._generation_lock_users.pop(session_id, None)
                if session_id not in self._expired_cleanup_claims:
                    self._generation_locks.pop(session_id, None)

    def _reclaim_expired_locked(self, limit: int) -> int:
        reclaimed = 0
        current = utc(self._clock())
        for session_id, record in list(self._items.items()):
            if reclaimed >= limit:
                break
            if session_id in self._closing or record.session.status == SessionStatus.CLOSED:
                continue
            if self._is_expired(record, current) and self._detach_expired_locked(session_id, record):
                reclaimed += 1
        return reclaimed

    def _detach_expired_locked(
        self,
        session_id: str,
        record: SessionRecord,
        *,
        enqueue: bool = True,
    ) -> SessionRecord | None:
        if enqueue and len(self._expired_pending) >= self._expired_pending_limit:
            self._metrics.expired_cleanup_dropped_total += 1
            return None
        was_closed = record.session.status == SessionStatus.CLOSED
        if not was_closed:
            self._mark_expired_locked(session_id, record)
        self._signal_stop_locked(session_id)
        self._signal_close_locked(session_id)
        self._close_claims.pop(session_id, None)
        self._closing.discard(session_id)
        self._clear_stop_timestamps_locked(session_id)
        snapshot = self._snapshot(record)
        self._items.pop(session_id, None)
        if enqueue:
            assert snapshot is not None
            key = self._pending_key(snapshot)
            if key in self._expired_pending_keys:
                self._metrics.expired_cleanup_duplicate_total += 1
                return snapshot
            self._expired_pending.append(snapshot)
            self._expired_pending_keys.add(key)
            self._after_pending_change_locked()
        return snapshot

    @staticmethod
    def _generation_token(session_id: str, generation_id: str | None) -> str:
        return generation_id or f"legacy:{session_id}"

    @classmethod
    def _pending_key(cls, record: SessionRecord) -> tuple[str, str]:
        session_id = record.session.session_id
        return session_id, cls._generation_token(session_id, record.generation_id)

    def _forget_pending_key_locked(self, key: tuple[str, str]) -> None:
        self._expired_pending_keys.discard(key)
        if self._expired_pending:
            self._expired_pending = deque(
                item for item in self._expired_pending if self._pending_key(item) != key
            )
        self._after_pending_change_locked()

    def _after_pending_change_locked(self) -> None:
        """Hook for stores that persist the bounded cleanup queue."""
        return


__all__ = ["SessionExpiryMixin"]
