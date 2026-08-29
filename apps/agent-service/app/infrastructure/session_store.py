"""Concurrency-safe in-memory session store with sliding TTL."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from ..domain.models import SessionRecord, SessionStatus, AvatarSession


class InMemorySessionStore:
    """Small replaceable store used by v0.1.0.

    The public methods are async so a Redis-backed implementation can be
    introduced later without changing application services.
    """

    def __init__(self, *, ttl_seconds: int = 1800, clock: Callable[[], datetime] | None = None) -> None:
        self.ttl_seconds = ttl_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._items: dict[str, SessionRecord] = {}
        self._lock = asyncio.Lock()

    async def create(self, session: AvatarSession) -> None:
        async with self._lock:
            self._items[session.session_id] = SessionRecord(session=session, last_activity=self._clock())

    async def get(self, session_id: str) -> SessionRecord | None:
        async with self._lock:
            record = self._items.get(session_id)
            if record is None:
                return None
            if self._is_expired(record, self._clock()):
                record.session.status = SessionStatus.EXPIRED
                return None
            return record

    async def touch(
        self,
        session_id: str,
        now: datetime | None = None,
        *,
        clear_interrupt: bool = False,
    ) -> None:
        async with self._lock:
            record = self._items.get(session_id)
            if record is None or record.session.status in {SessionStatus.CLOSED, SessionStatus.EXPIRED}:
                return
            current = now or self._clock()
            record.last_activity = current
            record.session.expires_at = current + timedelta(seconds=self.ttl_seconds)
            if clear_interrupt:
                record.interrupted = False
            if record.session.status == SessionStatus.INTERRUPTED and record.interrupted is False:
                record.session.status = SessionStatus.ACTIVE

    async def begin_run(self, session_id: str) -> str | None:
        """Open a resumable run and supersede any older run for this session."""
        async with self._lock:
            record = self._items.get(session_id)
            if record is None or self._is_expired(record, self._clock()):
                return None
            if record.session.status == SessionStatus.CLOSED:
                return None
            run_id = uuid4().hex
            record.active_run_id = run_id
            record.interrupted = False
            record.session.status = SessionStatus.ACTIVE
            current = self._clock()
            record.last_activity = current
            record.session.expires_at = current + timedelta(seconds=self.ttl_seconds)
            return run_id

    async def is_interrupted(self, session_id: str, run_id: str | None = None) -> bool:
        async with self._lock:
            record = self._items.get(session_id)
            if record is None or self._is_expired(record, self._clock()):
                return True
            if record.session.status in {SessionStatus.CLOSED, SessionStatus.EXPIRED}:
                return True
            # A newer request owns the session now; the previous graph run
            # must yield to it rather than writing more provider output.
            if run_id is not None and record.active_run_id != run_id:
                return True
            return record.interrupted

    async def mark_interrupted(self, session_id: str, run_id: str | None = None) -> SessionRecord | None:
        async with self._lock:
            record = self._items.get(session_id)
            if record is None or self._is_expired(record, self._clock()):
                return None
            if run_id is not None and record.active_run_id not in {None, run_id}:
                return record
            if record.session.status != SessionStatus.CLOSED:
                record.interrupted = True
                record.session.status = SessionStatus.INTERRUPTED
            return record

    async def close(self, session_id: str) -> SessionRecord | None:
        async with self._lock:
            record = self._items.get(session_id)
            if record is None:
                return None
            if self._is_expired(record, self._clock()) and record.session.status != SessionStatus.CLOSED:
                record.session.status = SessionStatus.EXPIRED
            else:
                record.session.status = SessionStatus.CLOSED
            record.interrupted = False
            record.active_run_id = None
            return record

    async def remove_expired(self, now: datetime | None = None) -> list[SessionRecord]:
        current = now or self._clock()
        async with self._lock:
            expired: list[SessionRecord] = []
            for session_id, record in list(self._items.items()):
                # Closed sessions still occupy memory until their TTL elapses.
                # Reclaim them here as well, while preserving CLOSED so the
                # application cleanup layer does not repeat provider teardown.
                if self._is_expired(record, current):
                    if record.session.status != SessionStatus.CLOSED:
                        record.session.status = SessionStatus.EXPIRED
                    expired.append(record)
                    del self._items[session_id]
            return expired

    async def list_for_user(self, user_id: str) -> list[SessionRecord]:
        async with self._lock:
            current = self._clock()
            return [
                record
                for record in self._items.values()
                if record.session.user_id == user_id and not self._is_expired(record, current)
            ]

    async def size(self) -> int:
        async with self._lock:
            return len(self._items)

    def _is_expired(self, record: SessionRecord, now: datetime) -> bool:
        return now >= record.session.expires_at or record.session.status == SessionStatus.EXPIRED
