"""Close-claim lifecycle for session stores.

The close path is kept separate from ordinary session reads and run steering.
It owns only in-memory claim state; provider I/O remains in the application
service and is coordinated through the generation token methods below.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
import time
from uuid import uuid4

from ..domain.models import SessionRecord, SessionStatus
from .session_metrics import SessionResourceMetrics
from .session_resources import utc


class SessionCloseLifecycleMixin:
    """Reusable close lifecycle for stores with an async lock.

    Concrete stores provide the record/event maps and the small locked helper
    methods used here. Keeping this protocol-free keeps the mixin usable by a
    future Redis-backed adapter without coupling it to the in-memory class.
    """

    _items: dict[str, SessionRecord]
    _closing: set[str]
    _close_claims: dict[str, str]
    _close_events: dict[str, asyncio.Event]
    _stop_requested_at: dict[tuple[str, str], float]
    _lock: asyncio.Lock
    _clock: Callable[[], datetime]
    _metrics: SessionResourceMetrics
    _close_generation_locks: dict[str, asyncio.Lock]

    async def claim_close(self, session_id: str) -> bool:
        """Atomically reserve a session for remote teardown.

        The claim invalidates the active run before the provider is touched.
        ``begin_run`` rejects the session while the claim is held, preventing
        a newly-created run from being closed by an older teardown request.
        """
        return (await self.claim_close_token(session_id)) is not None

    async def claim_close_token(self, session_id: str) -> str | None:
        """Return a generation token for an atomically-owned close claim."""
        acquire_generation = getattr(self, "_acquire_generation_lock", None)
        release_generation = getattr(self, "_release_generation_lock", None)
        generation_lock: asyncio.Lock | None = None
        claimed = False
        if callable(acquire_generation):
            generation_lock = await acquire_generation(session_id)
        try:
            async with self._lock:
                record = self._items.get(session_id)
                # Check the close lease before TTL so a wall-clock advance
                # cannot invalidate an in-flight provider teardown.
                if record is None or session_id in self._closing:
                    return None
                if self._is_expired(record, self._clock()):
                    return None
                if record.session.status == SessionStatus.CLOSED:
                    return None
                claim_token = uuid4().hex
                self._closing.add(session_id)
                self._close_claims[session_id] = claim_token
                if generation_lock is not None:
                    self._close_generation_locks[session_id] = generation_lock
                record.interrupted = True
                record.session.status = SessionStatus.INTERRUPTED
                if record.active_run_id:
                    self._record_stop_locked(session_id, record.active_run_id)
                record.active_run_id = None
                self._signal_stop_locked(session_id)
                self._close_events[session_id] = asyncio.Event()
                self._metrics.close_claims_total += 1
                claimed = True
                return claim_token
        finally:
            if generation_lock is not None and not claimed and callable(release_generation):
                await asyncio.shield(
                    self._release_generation_claim(session_id, generation_lock, release_generation)
                )

    async def is_closing(self, session_id: str) -> bool:
        async with self._lock:
            return session_id in self._closing

    async def wait_for_close(self, session_id: str) -> None:
        """Wait for an in-flight close claim to settle, if one exists."""
        async with self._lock:
            event = self._close_events.get(session_id)
            if event is None:
                return
        await event.wait()

    async def interruption_latency_ms(
        self,
        session_id: str,
        run_id: str | None = None,
        *,
        consume: bool = False,
    ) -> float | None:
        """Return elapsed time since a concrete run was asked to stop."""

        if not run_id:
            return None
        async with self._lock:
            started = self._stop_requested_at.get((session_id, run_id))
            if consume:
                self._stop_requested_at.pop((session_id, run_id), None)
        if started is None:
            return None
        return round(max(0.0, (time.perf_counter() - started) * 1000), 2)

    async def abort_close(
        self,
        session_id: str,
        *,
        claim_token: str | None = None,
    ) -> SessionRecord | None:
        """Release a failed close claim while keeping the run interrupted."""
        release_generation = getattr(self, "_release_generation_lock", None)
        generation_lock: asyncio.Lock | None = None
        async with self._lock:
            record = self._items.get(session_id)
            current_claim = self._close_claims.get(session_id)
            # A stale provider teardown must not release a replacement claim.
            if claim_token is not None and current_claim != claim_token:
                return self._snapshot(record)
            close_generation_locks = getattr(self, "_close_generation_locks", None)
            if close_generation_locks is not None:
                # Remove the mapping while the store lock is held. A waiter
                # can acquire the same asyncio.Lock immediately after release
                # and create a fresh claim; an old releaser must not remove
                # that new mapping later.
                generation_lock = close_generation_locks.pop(session_id, None)
            self._closing.discard(session_id)
            self._close_claims.pop(session_id, None)
            if record is not None and record.session.status != SessionStatus.CLOSED:
                record.interrupted = True
                record.active_run_id = None
                record.session.status = SessionStatus.INTERRUPTED
            self._signal_close_locked(session_id)
            self._metrics.close_aborted_total += 1
            snapshot = self._snapshot(record)
        if generation_lock is not None and callable(release_generation):
            await asyncio.shield(
                self._release_generation_claim(session_id, generation_lock, release_generation)
            )
        return snapshot

    async def complete_close(
        self,
        session_id: str,
        *,
        claim_token: str | None = None,
    ) -> SessionRecord | None:
        """Finalize only the close claim owned by the current generation.

        A session id may be reused by a provider after a close starts. If the
        claim disappeared in that window, returning ``None`` prevents the old
        teardown from closing the newly-created record.
        """
        release_generation = getattr(self, "_release_generation_lock", None)
        generation_lock: asyncio.Lock | None = None
        async with self._lock:
            if session_id not in self._closing:
                return None
            current_claim = self._close_claims.get(session_id)
            if claim_token is not None and current_claim != claim_token:
                return None
            close_generation_locks = getattr(self, "_close_generation_locks", None)
            if close_generation_locks is not None:
                # Pop under the store lock before handing the lease back so a
                # subsequent generation cannot be mistaken for this claim.
                generation_lock = close_generation_locks.pop(session_id, None)
            record = self._items.get(session_id)
            if record is None:
                self._closing.discard(session_id)
                self._close_claims.pop(session_id, None)
                self._signal_close_locked(session_id)
                snapshot = None
            else:
                record.session.status = SessionStatus.CLOSED
                snapshot = self._finish_close_locked(session_id, record)
        if generation_lock is not None and callable(release_generation):
            await asyncio.shield(
                self._release_generation_claim(session_id, generation_lock, release_generation)
            )
        return snapshot

    async def _release_generation_claim(
        self,
        session_id: str,
        generation_lock: asyncio.Lock,
        release_generation: Callable[[str, asyncio.Lock], object],
    ) -> None:
        await release_generation(session_id, generation_lock)

    async def close(self, session_id: str) -> SessionRecord | None:
        """Finalize a close claim, or atomically close when called directly."""
        async with self._lock:
            record = self._items.get(session_id)
            if record is None:
                return None
            was_closing = session_id in self._closing
            if was_closing:
                # A caller without the claim token must not finalize a remote
                # close that is still in flight.
                return self._snapshot(record)
            if (
                self._is_expired(record, self._clock())
                and record.session.status != SessionStatus.CLOSED
            ):
                record.session.status = SessionStatus.EXPIRED
            else:
                record.session.status = SessionStatus.CLOSED
            return self._finish_close_locked(session_id, record)

    def _is_expired(self, record: SessionRecord, now: datetime) -> bool:
        return utc(now) >= utc(record.session.expires_at) or record.session.status == SessionStatus.EXPIRED

    def _signal_stop_locked(self, session_id: str) -> None:
        if event := self._stop_events.pop(session_id, None):
            event.set()
            self._metrics.stop_signals_total += 1

    def _signal_close_locked(self, session_id: str) -> None:
        if event := self._close_events.pop(session_id, None):
            event.set()

    @staticmethod
    def _snapshot(record: SessionRecord | None) -> SessionRecord | None:
        return record.model_copy(deep=True) if record is not None else None

    def _record_stop_locked(self, session_id: str, run_id: str) -> None:
        self._stop_requested_at[(session_id, run_id)] = time.perf_counter()
        while len(self._stop_requested_at) > 4096:
            self._stop_requested_at.pop(next(iter(self._stop_requested_at)))

    def _clear_stop_timestamps_locked(self, session_id: str) -> None:
        for key in [item for item in self._stop_requested_at if item[0] == session_id]:
            self._stop_requested_at.pop(key, None)

    def _finish_close_locked(self, session_id: str, record: SessionRecord) -> SessionRecord:
        record.interrupted = False
        record.active_run_id = None
        self._closing.discard(session_id)
        self._close_claims.pop(session_id, None)
        self._signal_stop_locked(session_id)
        self._signal_close_locked(session_id)
        self._clear_stop_timestamps_locked(session_id)
        self._metrics.close_completed_total += 1
        snapshot = self._snapshot(record)
        assert snapshot is not None
        return snapshot
