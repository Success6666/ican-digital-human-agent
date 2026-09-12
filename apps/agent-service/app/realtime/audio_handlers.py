"""Audio frame handlers kept separate from text/run orchestration."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from ..graph.runtime_support import safe_error
from .audio import AudioIngressError
from .protocol import RealtimeMessage, require_audio_start


class RealtimeAudioHandlersMixin:
    """Handle bounded PCM ingress and explicit ASR capability reporting."""

    async def _audio_start(self, message: RealtimeMessage) -> None:
        require_audio_start(message)
        revision = message.revision or 1
        utterance_id = message.utterance_id or f"utt-{uuid4().hex}"
        ticket = await self.state.reserve_revision(utterance_id, revision)
        if ticket is None:
            await self._emit(
                "ack", request_id=message.request_id, action="audio_start", accepted=False,
                reason="stale_revision", utterance_id=utterance_id, revision=revision,
            )
            return
        committed = False
        try:
            await self._clear_audio(reason="audio_restarted")
            old = await self._stop_active()
            if old is not None:
                await self._publish_interrupted(old, reason="audio_started")
            stats = await self.ingress.start(utterance_id, revision)
            committed = True
        finally:
            if not committed:
                await self.state.rollback_revision(ticket)
        self.telemetry.asr_started(utterance_id=utterance_id, revision=revision)
        await self.state.start_audio(utterance_id, revision)
        await self._emit(
            "ack", request_id=message.request_id, action="audio_start", accepted=True,
            utterance_id=utterance_id, revision=revision,
        )
        await self._audio_queue(stats)

    async def _binary(self, frame: bytes) -> None:
        if not await self.state.audio_matches():
            await self._send_error("audio_not_started", "请先发送 audio_start")
            return
        try:
            stats = await self.ingress.push(frame)
        except AudioIngressError as exc:
            await self._send_error(exc.code, exc.message, close=exc.close)
            if exc.close:
                self.stop_event.set()
            return
        await self._audio_queue(stats)

    async def _audio_end(self, message: RealtimeMessage) -> None:
        if not await self.state.audio_matches(message.utterance_id, message.revision):
            await self._emit(
                "ack", request_id=message.request_id, action="audio_end", accepted=False,
                reason="no_active_audio",
            )
            return
        current = await self.state.finish_audio()
        try:
            result = await self.ingress.finish()
        except asyncio.CancelledError:
            self.telemetry.asr_finished(
                utterance_id=current[0] if current else None,
                revision=current[1] if current else None,
                status="error", reason="cancelled", text_length=0,
            )
            await self._reset_ingress_safely()
            raise
        except Exception as exc:
            self.telemetry.asr_finished(
                utterance_id=current[0] if current else None,
                revision=current[1] if current else None,
                status="error", reason="audio_finish_failed", text_length=0,
            )
            await self._send_error("audio_finish_failed", safe_error(exc))
            await self._emit(
                "ack", request_id=message.request_id, action="audio_end", accepted=False,
                reason="audio_finish_failed",
                utterance_id=current[0] if current else None,
                revision=current[1] if current else None,
            )
            return
        finally:
            await self._reset_ingress_safely()
        self.telemetry.asr_finished(
            utterance_id=current[0] if current else result.utterance_id,
            revision=current[1] if current else result.revision,
            status=result.status,
            reason=result.reason,
            text_length=len(result.text or ""),
        )
        await self._emit(
            "transcript", request_id=message.request_id,
            utterance_id=current[0] if current else result.utterance_id,
            revision=current[1] if current else result.revision, status=result.status,
            source="asr", text=result.text, reason=result.reason,
        )
        await self._emit(
            "ack", request_id=message.request_id, action="audio_end", accepted=True,
            utterance_id=current[0] if current else None, revision=current[1] if current else None,
        )
        if result.status == "final" and result.text and current:
            # ASR is the input boundary for the same realtime run. Reuse the
            # audio generation so the transcript cannot be stranded as a UI
            # event without reaching the Agent graph.
            await self._text(
                RealtimeMessage(
                    type="text",
                    requestId=message.request_id,
                    sessionId=self.state.session_id,
                    utteranceId=current[0],
                    revision=current[1],
                    text=result.text,
                    isFinal=True,
                )
            )

    async def _reset_ingress_safely(self) -> None:
        try:
            await self.ingress.reset()
        except Exception:
            # Cleanup errors must not hide the protocol result.
            return

    async def _audio_queue(self, stats: Any) -> None:
        self.telemetry.asr_buffered(
            utterance_id=getattr(stats, "utterance_id", None),
            frames=getattr(stats, "frames", 0),
            received_bytes=getattr(stats, "bytes_received", 0),
            buffered_bytes=getattr(stats, "buffered_bytes", 0),
            dropped_frames=getattr(stats, "dropped_frames", 0),
            capacity_bytes=self.limits.max_audio_buffer_bytes,
        )
        await self._emit(
            "audio_queue", utterance_id=getattr(stats, "utterance_id", None),
            revision=getattr(stats, "revision", None),
            status=getattr(stats, "status", "buffering"), frames=getattr(stats, "frames", 0),
            bytesReceived=getattr(stats, "bytes_received", 0),
            bufferedBytes=getattr(stats, "buffered_bytes", 0),
            droppedFrames=getattr(stats, "dropped_frames", 0),
            capacityBytes=self.limits.max_audio_buffer_bytes,
        )


__all__ = ["RealtimeAudioHandlersMixin"]
