from __future__ import annotations

import base64
import json

import httpx
import pytest

from app.realtime.audio import AudioFormat
from app.realtime.limits import RealtimeLimits
from app.realtime.media import (
    HttpAsrIngress,
    HttpTtsOutput,
    _should_trust_environment_proxy,
)


def test_http_asr_bypasses_environment_proxy_for_compose_service() -> None:
    assert _should_trust_environment_proxy("http://asr-service:7000/transcribe") is False
    assert _should_trust_environment_proxy("https://asr.example/transcribe") is True


@pytest.mark.asyncio
async def test_http_asr_posts_bounded_pcm_and_reads_transcript() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["content_type"] = request.headers["content-type"]
        seen["size"] = len(request.content)
        return httpx.Response(200, json={"text": "你好，数字人"})

    ingress = HttpAsrIngress(endpoint="https://asr.test/transcribe")
    await ingress._client.aclose()
    ingress._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await ingress.start("utt-1", 1)
    await ingress.push(b"\x00" * AudioFormat().frame_bytes)
    result = await ingress.finish()
    await ingress.close()
    assert result.status == "final"
    assert result.text == "你好，数字人"
    assert seen == {"content_type": "audio/pcm;rate=16000;channels=1", "size": 640}


@pytest.mark.asyncio
async def test_http_tts_supports_json_base64_and_chunks_output() -> None:
    payload = b"\x01\x02" * 400

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["text"] == "你好"
        return httpx.Response(200, json={"audioBase64": base64.b64encode(payload).decode()})

    output = HttpTtsOutput(endpoint="https://tts.test/synthesize", chunk_bytes=320)
    await output._client.aclose()
    output._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    chunks = [chunk async for chunk in output.synthesize("你好", run_id="run-1")]
    await output.close()
    assert len(chunks) == 3
    assert b"".join(chunks) == payload


@pytest.mark.asyncio
async def test_http_asr_keeps_the_newest_audio_instead_of_rejecting_a_long_question() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["size"] = len(request.content)
        seen["tail"] = bytes(request.content[-640:])
        return httpx.Response(200, json={"text": "长问题"})

    # Four frames of headroom, pushed eight: the budget is spent halfway through.
    limits = RealtimeLimits(
        max_audio_buffer_bytes=640 * 4,
        max_audio_frame_bytes=640,
        idle_timeout_seconds=2,
        heartbeat_interval_seconds=1,
    )
    ingress = HttpAsrIngress(endpoint="https://asr.test/transcribe", limits=limits)
    await ingress._client.aclose()
    ingress._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await ingress.start("utt-long", 1)

    latest = None
    for index in range(8):
        # Every frame carries a distinct byte so the retained window is provable.
        latest = await ingress.push(bytes([index + 1]) * 640)

    assert latest is not None
    # Overflow degrades to the bounded ring instead of raising: a rejected frame
    # used to be reported as an `error` frame *and* cost the rest of the question.
    assert latest.status == "dropping"
    assert latest.dropped_frames == 4
    assert latest.buffered_bytes == limits.max_audio_buffer_bytes
    assert len(ingress._buffer) == limits.max_audio_buffer_bytes
    # Whole frames only: a fractional trim would shift the PCM sample grid.
    assert len(ingress._buffer) % AudioFormat().frame_bytes == 0

    result = await ingress.finish()
    await ingress.close()
    assert result.status == "final"
    # The ASR request carries the retained window, and it is the newest audio:
    # frames 5-8 survive, frames 1-4 are the ones dropped.
    assert seen["size"] == limits.max_audio_buffer_bytes
    assert seen["tail"] == bytes([8]) * 640
