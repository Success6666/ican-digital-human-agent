"""Bounded resource budgets for one realtime WebSocket connection."""

from __future__ import annotations

import math
from dataclasses import dataclass

# The negotiated input format is PCM16, 16 kHz, mono, in 20 ms frames. These two
# constants are what turn a human-facing "how many seconds may a question be"
# setting into the byte budget the ring actually enforces.
PCM16_BYTES_PER_SECOND = 32_000
PCM16_FRAME_BYTES = 640


def audio_buffer_bytes_for_seconds(seconds: float) -> int:
    """Whole-frame byte budget for ``seconds`` of PCM16 16 kHz mono audio.

    Rounding up to a whole frame matters: a budget that is not frame aligned
    would let the ring trim a partial frame, which shifts the PCM sample grid and
    turns the tail of a long question into noise.
    """
    frames = max(1, math.ceil(max(0.0, seconds) * PCM16_BYTES_PER_SECOND / PCM16_FRAME_BYTES))
    return frames * PCM16_FRAME_BYTES


@dataclass(frozen=True, slots=True)
class RealtimeLimits:
    """Hard limits shared by protocol parsing, queues and lifecycle tasks."""

    control_frame_bytes: int = 64 * 1024
    audio_frame_bytes: int = 640  # PCM16, 16 kHz, mono, 20 ms.
    max_audio_frame_bytes: int = 4096
    # 60 s of PCM16 16 kHz mono (32 000 B/s) — exactly 3 000 whole frames. ASR runs
    # once, on `audio_end`, so the buffer has to hold the entire utterance: the old
    # 256 KiB budget covered barely 8 s and truncated any longer question. The
    # default is only a fallback; ``main`` derives it from
    # ``REALTIME_MAX_AUDIO_BUFFER_SECONDS`` so the budget can be tuned without a
    # code change.
    max_audio_buffer_bytes: int = 1_920_000
    outbound_queue_size: int = 128
    max_pending_runs: int = 2
    # How many TTS requests may be in flight at once, and how long one text
    # segment may wait for a slot. The old code waited 50 ms and then dropped the
    # segment in silence, which is far shorter than a real synthesis request, so a
    # busy server produced a reply with holes in it and no trace of why.
    tts_concurrency: int = 2
    tts_queue_timeout_seconds: float = 5.0
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
            self.tts_concurrency,
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
            self.tts_queue_timeout_seconds,
        )
        if any(not math.isfinite(value) or value <= 0 for value in positive_timeouts):
            raise ValueError("realtime timeouts must be finite and positive")
        if self.idle_timeout_seconds <= self.heartbeat_interval_seconds:
            raise ValueError("idle timeout must exceed heartbeat interval")


DEFAULT_LIMITS = RealtimeLimits()


__all__ = [
    "DEFAULT_LIMITS",
    "PCM16_BYTES_PER_SECOND",
    "PCM16_FRAME_BYTES",
    "RealtimeLimits",
    "audio_buffer_bytes_for_seconds",
]
