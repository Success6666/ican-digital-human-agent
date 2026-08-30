"""Bounded session-resource counters shared by local lifecycle adapters."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SessionResourceMetrics:
    """Process-local counters that make lifecycle reclamation observable.

    Counters are deliberately kept separate from the session map.  A future
    shared-store adapter can expose the same names from Redis metrics without
    changing application code, while the local implementation only mutates
    them while holding its store lock.
    """

    created_total: int = 0
    replaced_total: int = 0
    capacity_rejected_total: int = 0
    expired_reclaimed_total: int = 0
    closed_reclaimed_total: int = 0
    expired_cleanup_requeued_total: int = 0
    expired_cleanup_dropped_total: int = 0
    expired_cleanup_skipped_replaced_total: int = 0
    expired_cleanup_duplicate_total: int = 0
    stop_signals_total: int = 0
    close_claims_total: int = 0
    close_completed_total: int = 0
    close_aborted_total: int = 0
    close_superseded_total: int = 0
    heartbeat_total: int = 0
    heartbeat_rejected_total: int = 0
    stale_touch_rejected_total: int = 0

    def snapshot(
        self,
        *,
        active_sessions: int,
        active_runs: int,
        closing_sessions: int,
        stop_watchers: int,
        close_waiters: int,
        stop_timestamps: int,
        max_sessions: int,
        cleanup_batch_size: int,
        idle_timeout_seconds: int,
    ) -> dict[str, int]:
        """Return a stable, human-readable resource snapshot."""

        return {
            "active_sessions": active_sessions,
            "active_runs": active_runs,
            "closing_sessions": closing_sessions,
            "stop_watchers": stop_watchers,
            "close_waiters": close_waiters,
            "stop_timestamps": stop_timestamps,
            "max_sessions": max_sessions,
            "cleanup_batch_size": cleanup_batch_size,
            "idle_timeout_seconds": idle_timeout_seconds,
            "created_total": self.created_total,
            "replaced_total": self.replaced_total,
            "capacity_rejected_total": self.capacity_rejected_total,
            "expired_reclaimed_total": self.expired_reclaimed_total,
            "closed_reclaimed_total": self.closed_reclaimed_total,
            "expired_cleanup_requeued_total": self.expired_cleanup_requeued_total,
            "expired_cleanup_dropped_total": self.expired_cleanup_dropped_total,
            "expired_cleanup_skipped_replaced_total": self.expired_cleanup_skipped_replaced_total,
            "expired_cleanup_duplicate_total": self.expired_cleanup_duplicate_total,
            "stop_signals_total": self.stop_signals_total,
            "close_claims_total": self.close_claims_total,
            "close_completed_total": self.close_completed_total,
            "close_aborted_total": self.close_aborted_total,
            "close_superseded_total": self.close_superseded_total,
            "heartbeat_total": self.heartbeat_total,
            "heartbeat_rejected_total": self.heartbeat_rejected_total,
            "stale_touch_rejected_total": self.stale_touch_rejected_total,
        }


__all__ = ["SessionResourceMetrics"]
