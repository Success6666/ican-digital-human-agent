from __future__ import annotations

import pytest

from app.realtime.audio import MockPcmIngress
from app.realtime.limits import RealtimeLimits


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
