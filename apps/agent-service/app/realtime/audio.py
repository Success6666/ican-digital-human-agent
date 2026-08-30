"""PCM16 ingress boundary used by the realtime gateway."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .limits import DEFAULT_LIMITS, RealtimeLimits


@dataclass(frozen=True, slots=True)
class AudioFormat:
    codec: str = "pcm_s16le"
    sample_rate: int = 16_000
    channels: int = 1
    frame_ms: int = 20

    @property
    def frame_bytes(self) -> int:
        return self.sample_rate * self.channels * 2 * self.frame_ms // 1000


@dataclass(frozen=True, slots=True)
class AudioIngressStats:
    utterance_id: str | None
    revision: int | None
    frames: int
    bytes_received: int
    buffered_bytes: int
    status: str
    dropped_frames: int = 0


@dataclass(frozen=True, slots=True)
class TranscriptResult:
    status: str
    text: str | None = None
    utterance_id: str | None = None
    revision: int | None = None
    reason: str | None = None


class AudioIngressError(ValueError):
    """Audio cannot be accepted under the negotiated format or budget."""

    def __init__(self, code: str, message: str, *, close: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.close = close


class AudioIngress(Protocol):
    format: AudioFormat

    async def start(self, utterance_id: str, revision: int) -> AudioIngressStats: ...

    async def push(self, frame: bytes) -> AudioIngressStats: ...

    async def finish(self) -> TranscriptResult: ...

    async def reset(self) -> None: ...


class MockPcmIngress:
    """Validate and count PCM frames without pretending to perform ASR.

    The implementation intentionally does not retain raw microphone bytes. It
    exercises frame boundaries, budgets and cleanup while returning an explicit
    ``unsupported`` transcript until a real ASR adapter is configured.
    """

    def __init__(self, *, limits: RealtimeLimits = DEFAULT_LIMITS, audio_format: AudioFormat | None = None) -> None:
        self.limits = limits
        self.format = audio_format or AudioFormat()
        if self.format.frame_bytes != limits.audio_frame_bytes:
            raise ValueError("audio format does not match configured frame budget")
        self.utterance_id: str | None = None
        self.revision: int | None = None
        self.frames = 0
        self.bytes_received = 0
        self.buffered_bytes = 0
        self.dropped_frames = 0

    async def start(self, utterance_id: str, revision: int) -> AudioIngressStats:
        await self.reset()
        self.utterance_id = utterance_id
        self.revision = revision
        return self.stats("listening")

    async def push(self, frame: bytes) -> AudioIngressStats:
        if self.utterance_id is None:
            raise AudioIngressError("audio_not_started", "请先发送 audio_start", close=False)
        if not isinstance(frame, bytes) or not frame:
            raise AudioIngressError("audio_empty", "音频帧不能为空", close=False)
        size = len(frame)
        if size > self.limits.max_audio_frame_bytes:
            raise AudioIngressError("audio_frame_too_large", "音频帧超过大小限制", close=True)
        if size % 2 != 0 or size % self.format.frame_bytes != 0:
            raise AudioIngressError("audio_frame_invalid", "音频帧长度不是完整 PCM16 帧", close=False)
        status = "buffering"
        available = self.limits.max_audio_buffer_bytes - self.buffered_bytes
        if size > available:
            # The mock has no decoder/ASR worker to drain bytes. Model a
            # bounded ring instead of rejecting every later frame forever:
            # oldest complete frames are dropped and the stream can recover.
            drop_bytes = size - available
            drop_frames = (drop_bytes + self.format.frame_bytes - 1) // self.format.frame_bytes
            self.buffered_bytes = max(0, self.buffered_bytes - drop_frames * self.format.frame_bytes)
            self.dropped_frames += drop_frames
            status = "dropping"
        self.frames += size // self.format.frame_bytes
        self.bytes_received += size
        self.buffered_bytes = min(self.limits.max_audio_buffer_bytes, self.buffered_bytes + size)
        return self.stats(status)

    async def finish(self) -> TranscriptResult:
        result = TranscriptResult(
            status="unsupported",
            utterance_id=self.utterance_id,
            revision=self.revision,
            reason="asr_unconfigured",
        )
        await self.reset()
        return result

    async def reset(self) -> None:
        self.utterance_id = None
        self.revision = None
        self.frames = 0
        self.bytes_received = 0
        self.buffered_bytes = 0
        self.dropped_frames = 0

    def stats(self, status: str) -> AudioIngressStats:
        return AudioIngressStats(
            utterance_id=self.utterance_id,
            revision=self.revision,
            frames=self.frames,
            bytes_received=self.bytes_received,
            buffered_bytes=self.buffered_bytes,
            status=status,
            dropped_frames=self.dropped_frames,
        )


__all__ = [
    "AudioFormat",
    "AudioIngress",
    "AudioIngressError",
    "AudioIngressStats",
    "MockPcmIngress",
    "TranscriptResult",
]
