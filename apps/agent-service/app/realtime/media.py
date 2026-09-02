"""Configurable HTTP ASR ingress and TTS audio output adapters."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from .audio import AudioFormat, AudioIngressError, AudioIngressStats, MockPcmIngress, TranscriptResult
from .limits import DEFAULT_LIMITS, RealtimeLimits


class HttpAsrIngress(MockPcmIngress):
    """Send bounded PCM16 utterances to an HTTP transcription endpoint."""

    def __init__(self, *, endpoint: str, api_key: str = "", timeout_seconds: float = 30.0,
                 max_response_bytes: int = 1_048_576, limits: RealtimeLimits = DEFAULT_LIMITS,
                 audio_format: AudioFormat | None = None) -> None:
        super().__init__(limits=limits, audio_format=audio_format)
        self.endpoint = endpoint.strip()
        self.api_key = api_key.strip()
        self.timeout_seconds = max(0.1, timeout_seconds)
        self.max_response_bytes = max(1024, max_response_bytes)
        self._buffer = bytearray()
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.timeout_seconds, connect=min(2.0, self.timeout_seconds)))

    async def start(self, utterance_id: str, revision: int) -> AudioIngressStats:
        await super().start(utterance_id, revision)
        self._buffer.clear()
        return self.stats("listening")

    async def push(self, frame: bytes) -> AudioIngressStats:
        stats = await super().push(frame)
        if len(self._buffer) + len(frame) > self.limits.max_audio_buffer_bytes:
            raise AudioIngressError("audio_buffer_full", "音频缓冲区已满", close=False)
        self._buffer.extend(frame)
        return stats

    async def finish(self) -> TranscriptResult:
        if not self.endpoint:
            return await super().finish()
        if not self._buffer:
            result = TranscriptResult(status="empty", utterance_id=self.utterance_id, revision=self.revision, reason="audio_empty")
            await self.reset()
            return result
        headers = {"Content-Type": "audio/pcm;rate=16000;channels=1"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            response = await self._client.post(self.endpoint, content=bytes(self._buffer), headers=headers)
            if response.status_code < 200 or response.status_code >= 300:
                return TranscriptResult(status="error", utterance_id=self.utterance_id, revision=self.revision, reason=f"asr_http_{response.status_code}")
            if len(response.content) > self.max_response_bytes:
                return TranscriptResult(status="error", utterance_id=self.utterance_id, revision=self.revision, reason="asr_response_too_large")
            text = _extract_text(response)
            return TranscriptResult(status="final" if text else "empty", text=text, utterance_id=self.utterance_id, revision=self.revision, reason=None if text else "asr_empty")
        except asyncio.TimeoutError:
            return TranscriptResult(status="error", utterance_id=self.utterance_id, revision=self.revision, reason="asr_timeout")
        except httpx.HTTPError:
            return TranscriptResult(status="error", utterance_id=self.utterance_id, revision=self.revision, reason="asr_unavailable")
        finally:
            await self.reset()

    async def reset(self) -> None:
        self._buffer.clear()
        await super().reset()

    async def close(self) -> None:
        await self._client.aclose()


class HttpTtsOutput:
    """Convert text to bounded audio chunks through an HTTP TTS endpoint."""

    enabled = True

    def __init__(self, *, endpoint: str, api_key: str = "", timeout_seconds: float = 8.0,
                 chunk_bytes: int = 640, max_response_bytes: int = 4_194_304) -> None:
        self.endpoint = endpoint.strip()
        self.api_key = api_key.strip()
        self.timeout_seconds = max(0.1, timeout_seconds)
        self.chunk_bytes = max(320, chunk_bytes - (chunk_bytes % 2))
        self.max_response_bytes = max(1024, max_response_bytes)
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.timeout_seconds, connect=min(2.0, self.timeout_seconds)))

    async def synthesize(self, text: str, *, run_id: str | None = None) -> AsyncIterator[bytes]:
        if not self.endpoint or not text.strip():
            return
        headers = {"Content-Type": "application/json", "Accept": "audio/pcm,audio/wav,application/octet-stream"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            response = await self._client.post(self.endpoint, json={"text": text, "runId": run_id, "format": "pcm_s16le", "sampleRate": 16000, "channels": 1}, headers=headers)
            if response.status_code < 200 or response.status_code >= 300 or len(response.content) > self.max_response_bytes:
                return
            payload = response.content
            if response.headers.get("content-type", "").startswith("application/json"):
                try:
                    body = response.json()
                    encoded = body.get("audioBase64") or body.get("audio")
                    if encoded:
                        import base64
                        payload = base64.b64decode(encoded, validate=True)
                except (ValueError, json.JSONDecodeError):
                    return
            for offset in range(0, len(payload), self.chunk_bytes):
                chunk = payload[offset : offset + self.chunk_bytes]
                if len(chunk) % 2 == 0 and chunk:
                    yield chunk
        except (httpx.HTTPError, asyncio.TimeoutError):
            return

    async def close(self) -> None:
        await self._client.aclose()


class NullAudioOutput:
    enabled = False

    async def synthesize(self, text: str, *, run_id: str | None = None) -> AsyncIterator[bytes]:
        if False:
            yield b""

    async def close(self) -> None:
        return


def _extract_text(response: httpx.Response) -> str | None:
    content_type = response.headers.get("content-type", "")
    if "json" not in content_type:
        return response.text.strip() or None
    try:
        body: Any = response.json()
    except (ValueError, json.JSONDecodeError):
        return None
    if isinstance(body, dict):
        for key in ("text", "transcript", "result"):
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


__all__ = ["HttpAsrIngress", "HttpTtsOutput", "NullAudioOutput"]
