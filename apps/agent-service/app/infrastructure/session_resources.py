"""Resource limits and lease helpers for local session stores."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import os
from ..domain.models import SessionRecord, SessionStatus
from .session_metrics import SessionResourceMetrics


class SessionResourceMixin:
    """Keep capacity, leases and counters separate from close coordination."""

    _items: dict[str, SessionRecord]
    _lock: asyncio.Lock
    _metrics: SessionResourceMetrics

    def _configure_resources(
        self,
        *,
        max_sessions: int | None,
        cleanup_batch_size: int | None,
        idle_timeout_seconds: int | None,
        ttl_seconds: int,
    ) -> None:
        self.max_sessions = _configured(max_sessions, "SESSION_MAX_SESSIONS", 1024, 100_000)
        self.cleanup_batch_size = _configured(cleanup_batch_size, "SESSION_CLEANUP_BATCH_SIZE", 100, 10_000)
        self.idle_timeout_seconds = _configured(
            idle_timeout_seconds,
            "SESSION_IDLE_TIMEOUT_SECONDS",
            ttl_seconds,
            86_400,
        )

    async def heartbeat(
        self,
        session_id: str,
        run_id: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        accepted = await self.touch(session_id, now, run_id=run_id, clear_interrupt=False)
        async with self._lock:
            counter = "heartbeat_total" if accepted else "heartbeat_rejected_total"
            setattr(self._metrics, counter, getattr(self._metrics, counter) + 1)
        return accepted

    async def stats(self) -> dict[str, int]:
        async with self._lock:
            counts = {status: 0 for status in SessionStatus}
            for record in self._items.values():
                counts[record.session.status] += 1
            return self._metrics.snapshot(
                active_sessions=counts[SessionStatus.ACTIVE] + counts[SessionStatus.INTERRUPTED],
                active_runs=sum(1 for record in self._items.values() if record.active_run_id),
                closing_sessions=len(self._closing),
                stop_watchers=len(self._stop_events),
                close_waiters=len(self._close_events),
                stop_timestamps=len(self._stop_requested_at),
                max_sessions=self.max_sessions,
                cleanup_batch_size=self.cleanup_batch_size,
                idle_timeout_seconds=self.idle_timeout_seconds,
            )

    def _reclaim_closed_locked(self, limit: int) -> int:
        reclaimed = 0
        for session_id, record in list(self._items.items()):
            if reclaimed >= limit or record.session.status != SessionStatus.CLOSED:
                continue
            del self._items[session_id]
            if event := self._stop_events.pop(session_id, None):
                event.set()
                self._metrics.stop_signals_total += 1
            if event := self._close_events.pop(session_id, None):
                event.set()
            self._close_claims.pop(session_id, None)
            self._closing.discard(session_id)
            self._clear_stop_timestamps_locked(session_id)
            self._metrics.closed_reclaimed_total += 1
            reclaimed += 1
        return reclaimed

    def _mark_expired_locked(self, session_id: str, record: SessionRecord) -> None:
        record.session.status = SessionStatus.EXPIRED
        record.interrupted = False

    def _renew_locked(self, record: SessionRecord, now: datetime) -> None:
        record.last_activity = now
        record.session.expires_at = now + timedelta(seconds=self.idle_timeout_seconds)


def _configured(value: int | None, env_name: str, default: int, upper: int) -> int:
    if value is None:
        raw = os.getenv(env_name)
        value = int(raw) if raw is not None else default
    if value <= 0 or value > upper:
        raise ValueError(f"{env_name.lower()} must be between 1 and {upper}")
    return value


def resource_limit(value: int | None, name: str, upper: int) -> int:
    if value is None:
        raise ValueError(f"{name} is required")
    if value <= 0 or value > upper:
        raise ValueError(f"{name} must be between 1 and {upper}")
    return value


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


__all__ = ["SessionResourceMixin", "resource_limit", "utc"]
