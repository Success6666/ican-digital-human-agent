"""Bounded resource budgets for one realtime WebSocket connection."""

from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class RealtimeLimits:
    """Hard limits shared by protocol parsing, queues and lifecycle tasks."""

    control_frame_bytes: int = 64 * 1024
    audio_frame_bytes: int = 640  # PCM16, 16 kHz, mono, 20 ms.
    max_audio_frame_bytes: int = 4096
    max_audio_buffer_bytes: int = 256 * 1024
    outbound_queue_size: int = 128
    max_pending_runs: int = 2
    handshake_timeout_seconds: float = 5.0
    heartbeat_interval_seconds: float = 15.0
    idle_timeout_seconds: float = 45.0
    interrupt_timeout_seconds: float = 0.25

    def __post_init__(self) -> None:
        positive_ints = (
            self.control_frame_bytes,
            self.audio_frame_bytes,
            self.max_audio_frame_bytes,
            self.max_audio_buffer_bytes,
            self.outbound_queue_size,
            self.max_pending_runs,
        )
        if any(not isinstance(value, int) or value <= 0 for value in positive_ints):
            raise ValueError("realtime integer limits must be positive")
        if self.max_audio_frame_bytes < self.audio_frame_bytes:
            raise ValueError("max_audio_frame_bytes must cover the default frame")
        positive_timeouts = (
            self.handshake_timeout_seconds,
            self.heartbeat_interval_seconds,
            self.idle_timeout_seconds,
            self.interrupt_timeout_seconds,
        )
        if any(not math.isfinite(value) or value <= 0 for value in positive_timeouts):
            raise ValueError("realtime timeouts must be finite and positive")
        if self.idle_timeout_seconds <= self.heartbeat_interval_seconds:
            raise ValueError("idle timeout must exceed heartbeat interval")


DEFAULT_LIMITS = RealtimeLimits()


__all__ = ["DEFAULT_LIMITS", "RealtimeLimits"]
