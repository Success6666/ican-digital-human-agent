"""Concurrency-safe in-memory session store with sliding TTL."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from ..domain.models import SessionRecord, SessionStatus
from .session_close import SessionCloseLifecycleMixin
from .session_expiry import SessionExpiryMixin
from .session_metrics import SessionResourceMetrics
from .session_resources import SessionResourceMixin, resource_limit, utc


class InMemorySessionStore(SessionCloseLifecycleMixin, SessionExpiryMixin, SessionResourceMixin):
    """Small replaceable store used by the local runtime.

    The public methods are async so a Redis-backed implementation can be
    introduced later without changing application services. All state
    transitions happen under one lock; remote provider I/O is coordinated by
    the application service after an atomic close claim.
    """

    def __init__(
        self,
        *,
        ttl_seconds: int = 1800,
        clock: Callable[[], datetime] | None = None,
        max_sessions: int | None = None,
        cleanup_batch_size: int | None = None,
        idle_timeout_seconds: int | None = None,
    ) -> None:
        self.ttl_seconds = resource_limit(ttl_seconds, "ttl_seconds", 86_400)
        self._configure_resources(
            max_sessions=max_sessions,
            cleanup_batch_size=cleanup_batch_size,
            idle_timeout_seconds=idle_timeout_seconds,
            ttl_seconds=ttl_seconds,
        )
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
        self._metrics = SessionResourceMetrics()
        self._init_expiry_lifecycle()

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
            if self._is_expired(record, utc(self._clock())):
                self._detach_expired_locked(session_id, record)
                return None
            return self._snapshot(record)

    async def touch(
        self,
        session_id: str,
        now: datetime | None = None,
        *,
        clear_interrupt: bool = False,
        run_id: str | None = None,
    ) -> bool:
        async with self._lock:
            record = self._items.get(session_id)
            if (
                record is None
                or session_id in self._closing
                or record.session.status in {SessionStatus.CLOSED, SessionStatus.EXPIRED}
            ):
                return False
            if run_id is not None and record.active_run_id != run_id:
                self._metrics.stale_touch_rejected_total += 1
                return False
            current = utc(now or self._clock())
            if self._is_expired(record, current):
                self._detach_expired_locked(session_id, record)
                return False
            self._renew_locked(record, current)
            if clear_interrupt:
                record.interrupted = False
            if record.session.status == SessionStatus.INTERRUPTED and record.interrupted is False:
                record.session.status = SessionStatus.ACTIVE
            return True

    async def begin_run(self, session_id: str, run_id: str | None = None) -> str | None:
        """Open a resumable run and supersede any older run for this session."""
        async with self._lock:
            record = self._items.get(session_id)
            if record is None:
                return None
            if session_id in self._closing or record.session.status == SessionStatus.CLOSED:
                return None
            if self._is_expired(record, utc(self._clock())):
                self._detach_expired_locked(session_id, record)
                return None
            previous_event = self._stop_events.get(session_id)
            if previous_event is not None:
                # Wake any provider task belonging to the superseded run.
                previous_event.set()
            previous_run_id = record.active_run_id
            if previous_run_id:
                self._record_stop_locked(session_id, previous_run_id)
            run_id = run_id or uuid4().hex
            record.active_run_id = run_id
            record.interrupted = False
            self._stop_events[session_id] = asyncio.Event()
            self._stop_requested_at.pop((session_id, run_id), None)
            record.session.status = SessionStatus.ACTIVE
            self._renew_locked(record, utc(self._clock()))
            return run_id

    async def is_interrupted(self, session_id: str, run_id: str | None = None) -> bool:
        async with self._lock:
            record = self._items.get(session_id)
            if record is None:
                return True
            if session_id in self._closing or record.session.status in {SessionStatus.CLOSED, SessionStatus.EXPIRED}:
                return True
            if self._is_expired(record, utc(self._clock())):
                self._detach_expired_locked(session_id, record)
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
                or record.session.status in {SessionStatus.CLOSED, SessionStatus.EXPIRED}
                or session_id in self._closing
                or record.active_run_id != run_id
                or record.interrupted
            ):
                return
            if self._is_expired(record, utc(self._clock())):
                self._detach_expired_locked(session_id, record)
                return
            event = self._stop_events.get(session_id)
            if event is None:
                return
        await event.wait()

    async def mark_interrupted(self, session_id: str, run_id: str | None = None) -> SessionRecord | None:
        async with self._lock:
            record = self._items.get(session_id)
            if record is None:
                return None
            if session_id in self._closing:
                # Close owns provider teardown; callers must not turn this
                # into a second provider interrupt while the claim is held.
                return self._snapshot(record)
            if record.session.status == SessionStatus.CLOSED:
                return self._snapshot(record)
            if self._is_expired(record, utc(self._clock())):
                self._detach_expired_locked(session_id, record)
                return None
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

    async def list_for_user(self, user_id: str, *, limit: int = 100) -> list[SessionRecord]:
        batch = resource_limit(limit, "limit", 10_000)
        async with self._lock:
            current = self._clock()
            result: list[SessionRecord] = []
            for record in self._items.values():
                if len(result) >= batch:
                    break
                if record.session.user_id == user_id and not self._is_expired(record, current):
                    result.append(self._snapshot(record))
            return result

    async def size(self) -> int:
        async with self._lock:
            return len(self._items)
