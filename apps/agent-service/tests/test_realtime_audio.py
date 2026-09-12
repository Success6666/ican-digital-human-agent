from __future__ import annotations

import pytest

from app.realtime.audio import MockPcmIngress
from app.realtime.limits import RealtimeLimits, audio_buffer_bytes_for_seconds


@pytest.mark.asyncio
async def test_pcm_ingress_stays_bounded_over_a_long_capture() -> None:
    limits = RealtimeLimits(
        max_audio_buffer_bytes=640 * 8,
        max_audio_frame_bytes=640,
        idle_timeout_seconds=2,
        heartbeat_interval_seconds=1,
    )
    ingress = MockPcmIngress(limits=limits)
    await ingress.start("utterance-1", 1)

    latest = None
    for _ in range(1_500):
        latest = await ingress.push(b"\x00" * 640)

    assert latest is not None
    assert latest.buffered_bytes <= limits.max_audio_buffer_bytes
    assert latest.dropped_frames > 0
    assert latest.frames == 1_500


def test_second_budget_rounds_up_to_whole_frames() -> None:
    # A budget that is not frame aligned would let the ring trim a partial
    # frame, shifting the PCM sample grid and turning the tail of a long
    # question into noise, so every derived budget must be a multiple of 640.
    assert audio_buffer_bytes_for_seconds(60) == 1_920_000
    assert audio_buffer_bytes_for_seconds(30) == 960_000
    for seconds in (0.1, 1, 7.5, 8.19, 8.2, 45.7, 300, 600):
        budget = audio_buffer_bytes_for_seconds(seconds)
        assert budget % 640 == 0
        assert budget >= seconds * 32_000
        # Rounding up must stay within one frame of the exact request.
        assert budget < seconds * 32_000 + 640


def test_second_budget_never_collapses_to_zero() -> None:
    assert audio_buffer_bytes_for_seconds(0) == 640
    assert audio_buffer_bytes_for_seconds(-5) == 640
