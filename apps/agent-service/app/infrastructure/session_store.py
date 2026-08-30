"""Concurrency-safe in-memory session store with sliding TTL."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import time
from uuid import uuid4

from ..domain.models import AvatarSession, SessionRecord, SessionStatus
from .session_close import SessionCloseLifecycleMixin


class InMemorySessionStore(SessionCloseLifecycleMixin):
    """Small replaceable store used by the local runtime.

    The public methods are async so a Redis-backed implementation can be
    introduced later without changing application services. All state
    transitions happen under one lock; remote provider I/O is coordinated by
    the application service after an atomic close claim.
    """

    def __init__(self, *, ttl_seconds: int = 1800, clock: Callable[[], datetime] | None = None) -> None:
        self.ttl_seconds = ttl_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._items: dict[str, SessionRecord] = {}
        self._stop_events: dict[str, asyncio.Event] = {}
        # ``close`` performs remote I/O outside the store lock. Keep a small
        # in-process claim set so it remains atomic with ``begin_run``.
        self._closing: set[str] = set()
        # A close claim is generation-scoped.  The session id can be reused
        # while an older provider teardown is still awaiting remote I/O; a
        # token keeps that old teardown from completing or aborting a newer
        # claim for the same id.
        self._close_claims: dict[str, str] = {}
        self._close_events: dict[str, asyncio.Event] = {}
        # Monotonic timestamps let the stream report cancellation latency
        # without relying on wall-clock adjustments. Entries are bounded and
        # removed when a run/session generation is replaced or finalized.
        self._stop_requested_at: dict[tuple[str, str], float] = {}
        self._lock = asyncio.Lock()

    async def create(self, session: AvatarSession) -> None:
        async with self._lock:
            # Replacing a session id must wake waiters attached to the old
            # generation; otherwise they can retain stale session references.
            previous_stop = self._stop_events.pop(session.session_id, None)
            if previous_stop is not None:
                previous_stop.set()
            previous_close = self._close_events.pop(session.session_id, None)
            if previous_close is not None:
                previous_close.set()
            self._close_claims.pop(session.session_id, None)
            self._closing.discard(session.session_id)
            self._clear_stop_timestamps_locked(session.session_id)
            self._items[session.session_id] = SessionRecord(
                session=session.model_copy(deep=True),
                last_activity=self._clock(),
            )
            self._stop_events[session.session_id] = asyncio.Event()

    async def get(self, session_id: str) -> SessionRecord | None:
        async with self._lock:
            record = self._items.get(session_id)
            if record is None:
                return None
            # A close claim owns the record until provider teardown settles.
            # Keep that snapshot available even if its original TTL elapses;
            # otherwise a concurrent DELETE could observe a false 404 while
            # the first close is still in flight.
            if record.session.status == SessionStatus.CLOSED or session_id in self._closing:
                return self._snapshot(record)
            if self._is_expired(record, self._clock()):
                record.session.status = SessionStatus.EXPIRED
                self._signal_stop_locked(session_id)
                self._signal_close_locked(session_id)
                return None
            return self._snapshot(record)

    async def touch(
        self,
        session_id: str,
        now: datetime | None = None,
        *,
        clear_interrupt: bool = False,
    ) -> None:
        async with self._lock:
            record = self._items.get(session_id)
            if (
                record is None
                or session_id in self._closing
                or record.session.status in {SessionStatus.CLOSED, SessionStatus.EXPIRED}
            ):
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
            if record.session.status == SessionStatus.CLOSED or session_id in self._closing:
                return None
            previous_event = self._stop_events.get(session_id)
            if previous_event is not None:
                # Wake any provider task belonging to the superseded run.
                previous_event.set()
            previous_run_id = record.active_run_id
            if previous_run_id:
                self._record_stop_locked(session_id, previous_run_id)
            run_id = uuid4().hex
            record.active_run_id = run_id
            record.interrupted = False
            self._stop_events[session_id] = asyncio.Event()
            self._stop_requested_at.pop((session_id, run_id), None)
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
            if record.session.status in {SessionStatus.CLOSED, SessionStatus.EXPIRED} or session_id in self._closing:
                return True
            # A newer request owns the session now; the previous graph run
            # must yield to it rather than writing more provider output.
            if run_id is not None and record.active_run_id != run_id:
                return True
            return record.interrupted

    async def wait_for_stop(self, session_id: str, run_id: str) -> None:
        """Wait for interruption or supersession of one concrete run.

        The event is captured while holding the store lock, so a stop racing
        with this call cannot be missed. Redis-backed stores can implement the
        same port with a pub/sub or keyspace notification.
        """
        async with self._lock:
            record = self._items.get(session_id)
            if (
                record is None
                or self._is_expired(record, self._clock())
                or record.session.status in {SessionStatus.CLOSED, SessionStatus.EXPIRED}
                or session_id in self._closing
                or record.active_run_id != run_id
                or record.interrupted
            ):
                return
            event = self._stop_events.get(session_id)
            if event is None:
                return
        await event.wait()

    async def mark_interrupted(self, session_id: str, run_id: str | None = None) -> SessionRecord | None:
        async with self._lock:
            record = self._items.get(session_id)
            if record is None or self._is_expired(record, self._clock()):
                return None
            if session_id in self._closing:
                # Close owns provider teardown; callers must not turn this
                # into a second provider interrupt while the claim is held.
                return self._snapshot(record)
            if run_id is not None and record.active_run_id not in {None, run_id}:
                return self._snapshot(record)
            target_run_id = run_id or record.active_run_id
            if target_run_id:
                self._record_stop_locked(session_id, target_run_id)
            if record.session.status != SessionStatus.CLOSED:
                record.interrupted = True
                record.session.status = SessionStatus.INTERRUPTED
            event = self._stop_events.get(session_id)
            if event is not None:
                event.set()
            return self._snapshot(record)

    async def remove_expired(self, now: datetime | None = None) -> list[SessionRecord]:
        current = now or self._clock()
        async with self._lock:
            expired: list[SessionRecord] = []
            for session_id, record in list(self._items.items()):
                # Do not remove a record while its provider teardown owns the
                # close lease. Otherwise cleanup can delete state before the
                # close operation settles.
                if session_id in self._closing:
                    continue
                if self._is_expired(record, current):
                    if record.session.status != SessionStatus.CLOSED:
                        record.session.status = SessionStatus.EXPIRED
                    self._signal_stop_locked(session_id)
                    self._signal_close_locked(session_id)
                    self._clear_stop_timestamps_locked(session_id)
                    expired.append(self._snapshot(record))
                    del self._items[session_id]
            return expired

    async def list_for_user(self, user_id: str) -> list[SessionRecord]:
        async with self._lock:
            current = self._clock()
            return [
                self._snapshot(record)
                for record in self._items.values()
                if record.session.user_id == user_id and not self._is_expired(record, current)
            ]

    async def size(self) -> int:
        async with self._lock:
            return len(self._items)

    def _is_expired(self, record: SessionRecord, now: datetime) -> bool:
        return now >= record.session.expires_at or record.session.status == SessionStatus.EXPIRED

    def _signal_stop_locked(self, session_id: str) -> None:
        event = self._stop_events.pop(session_id, None)
        if event is not None:
            event.set()

    def _signal_close_locked(self, session_id: str) -> None:
        event = self._close_events.pop(session_id, None)
        if event is not None:
            event.set()

    @staticmethod
    def _snapshot(record: SessionRecord | None) -> SessionRecord | None:
        """Keep callers from mutating state outside the store lock."""
        return record.model_copy(deep=True) if record is not None else None

    def _record_stop_locked(self, session_id: str, run_id: str) -> None:
        self._stop_requested_at[(session_id, run_id)] = time.perf_counter()
        # Keep the map bounded even if callers create many short-lived runs.
        while len(self._stop_requested_at) > 4096:
            self._stop_requested_at.pop(next(iter(self._stop_requested_at)))

    def _clear_stop_timestamps_locked(self, session_id: str) -> None:
        for key in [item for item in self._stop_requested_at if item[0] == session_id]:
            self._stop_requested_at.pop(key, None)
