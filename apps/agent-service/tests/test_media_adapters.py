from __future__ import annotations

import base64
import json

import httpx
import pytest

from app.realtime.audio import AudioFormat
from app.realtime.media import HttpAsrIngress, HttpTtsOutput, _should_trust_environment_proxy


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
