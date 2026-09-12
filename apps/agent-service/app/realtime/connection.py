"""Authenticated realtime WebSocket connection and run lifecycle."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from ..application.errors import ApplicationError, SessionNotFoundError
from ..domain.models import SessionStatus
from ..graph.runtime_support import safe_error
from .audio import AudioIngress, MockPcmIngress
from .auth import RealtimeIdentity, read_identity, reject
from .handlers import RealtimeHandlersMixin
from .lifecycle import RealtimeLifecycleMixin
from .limits import DEFAULT_LIMITS, RealtimeLimits
from .observability import RealtimeTelemetry
from .protocol import (
    MessageType,
    RealtimeMessage,
    RealtimeProtocolError,
    event_payload,
    parse_control,
    require_hello,
)
from .state import BoundedOutboundQueue, ConnectionState, RealtimeBackpressureError


class RealtimeConnection(RealtimeHandlersMixin, RealtimeLifecycleMixin):
    """One authenticated socket; all outbound writes go through one writer."""

    def __init__(
        self,
        websocket: WebSocket,
        container: Any,
        *,
        limits: RealtimeLimits = DEFAULT_LIMITS,
        ingress: AudioIngress | None = None,
        output: Any | None = None,
    ) -> None:
        self.websocket = websocket
        self.container = container
        self.limits = limits
        self.state = ConnectionState()
        self.telemetry = RealtimeTelemetry(
            getattr(container, "observability", None), self.state.connection_id
        )
        self.queue = BoundedOutboundQueue(limits.outbound_queue_size)
        self.ingress = ingress or MockPcmIngress(limits=limits)
        self.audio_output = output or getattr(container, "audio_output", None)
        self._tts_semaphore = asyncio.Semaphore(limits.tts_concurrency)
        self.stop_event = asyncio.Event()
        self.run_tasks: dict[str, asyncio.Task[Any]] = {}
        self.background_tasks: set[asyncio.Task[Any]] = set()
        self.cancelled_runs: set[str] = set()
        self.completed_runs: set[str] = set()
        self.terminal_runs: set[str] = set()
        self._emit_lock = asyncio.Lock()
        self._writer_task: asyncio.Task[Any] | None = None
        self._heartbeat_task: asyncio.Task[Any] | None = None
        self._close_task: asyncio.Task[Any] | None = None
        self._close_code = 1000
        self._accepted = False
        self._writer_failed = False

    async def run(self) -> None:
        identity = read_identity(self.websocket, self.container.settings.internal_token)
        if identity is None:
            await reject(self.websocket)
            return
        await self.websocket.accept()
        self._accepted = True
        self._writer_task = asyncio.create_task(self._writer(), name=f"realtime-writer-{self.state.connection_id}")
        try:
            if not await self._handshake(identity):
                return
            self._heartbeat_task = asyncio.create_task(self._heartbeat(), name=f"realtime-heartbeat-{self.state.connection_id}")
            await self._serve_transport()
        finally:
            await self._shutdown()

    async def _serve_transport(self) -> None:
        """Stop a blocked receive loop when the single writer loses the socket."""
        receive_task = asyncio.create_task(
            self._receive_loop(), name=f"realtime-receive-{self.state.connection_id}"
        )
        writer_task = self._writer_task
        wait_set = {receive_task}
        if writer_task is not None:
            wait_set.add(writer_task)
        done, _ = await asyncio.wait(wait_set, return_when=asyncio.FIRST_COMPLETED)
        if writer_task is not None and writer_task in done and not receive_task.done():
            self.stop_event.set()
            receive_task.cancel()
        await asyncio.gather(receive_task, return_exceptions=True)
        # Consume a completed writer result here; _shutdown also awaits it,
        # but doing so makes transport failures deterministic in tests.
        for task in done:
            if task is not receive_task:
                await asyncio.gather(task, return_exceptions=True)

    async def _handshake(self, identity: RealtimeIdentity) -> bool:
        try:
            frame = await asyncio.wait_for(self.websocket.receive(), self.limits.handshake_timeout_seconds)
            if frame.get("type") == "websocket.disconnect":
                return False
            raw = frame.get("text")
            if raw is None:
                raise RealtimeProtocolError("hello_required", "连接建立后必须先发送 hello", close=True)
            message = parse_control(raw, max_bytes=self.limits.control_frame_bytes)
            require_hello(message)
            record = await self.container.session_service.get_for_user(
                user_id=identity.user_id,
                session_id=message.session_id or "",
            )
            if record.session.status == SessionStatus.CLOSED:
                raise SessionNotFoundError("会话已关闭，请重新建立会话")
        except WebSocketDisconnect:
            return False
        except asyncio.TimeoutError:
            await self._send_error("handshake_timeout", "hello 握手超时", close=True)
            return False
        except (RealtimeProtocolError, ApplicationError) as exc:
            await self._send_error(_error_code(exc), _error_message(exc), close=True)
            return False
        await self.state.bind(
            user_id=identity.user_id,
            user_name=identity.user_name,
            session_id=message.session_id or "",
        )
        self.telemetry.bind(owner_id=identity.user_id, session_id=self.state.session_id or "")
        await self._emit(
            "ready",
            request_id=message.request_id,
            session_id=self.state.session_id,
            protocol="realtime.v1",
            connectionId=self.state.connection_id,
            heartbeatMs=round(self.limits.heartbeat_interval_seconds * 1000),
            capabilities={
                "textInput": True,
                "audioInput": True,
                "audioOutput": bool(getattr(self.audio_output, "enabled", False)),
                "asr": "supported" if self.ingress.__class__.__name__ == "HttpAsrIngress" else "unsupported",
                "tts": "supported" if bool(getattr(self.audio_output, "enabled", False)) else "unsupported",
                "interrupt": True,
            },
            audioFormat={
                "codec": self.ingress.format.codec,
                "sampleRate": self.ingress.format.sample_rate,
                "channels": self.ingress.format.channels,
                "frameMs": self.ingress.format.frame_ms,
            },
            limits={
                "controlFrameBytes": self.limits.control_frame_bytes,
                "audioFrameBytes": self.limits.audio_frame_bytes,
                "maxAudioBufferBytes": self.limits.max_audio_buffer_bytes,
                "outboundQueueSize": self.limits.outbound_queue_size,
            },
        )
        self.telemetry.ready()
        return True

    async def _receive_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                frame = await self.websocket.receive()
            except WebSocketDisconnect:
                return
            frame_type = frame.get("type")
            if frame_type == "websocket.disconnect":
                return
            if frame_type != "websocket.receive":
                continue
            self.state.touch()
            if frame.get("text") is not None:
                await self._control(frame["text"])
            elif frame.get("bytes") is not None:
                await self._binary(frame["bytes"])

    async def _control(self, raw: str) -> None:
        try:
            message = parse_control(raw, max_bytes=self.limits.control_frame_bytes)
            await self._dispatch(message)
        except RealtimeProtocolError as exc:
            await self._send_error(exc.code, exc.message, request_id=_request_id(raw), close=exc.close)
        except ApplicationError as exc:
            await self._send_error("request_rejected", _error_message(exc), close=False)
        except Exception as exc:  # transport must never expose a traceback
            await self._send_error("request_failed", safe_error(exc), close=False)

    async def _dispatch(self, message: RealtimeMessage) -> None:
        if not self.state.hello_received:
            raise RealtimeProtocolError("hello_required", "连接建立后必须先发送 hello", close=True)
        if message.session_id and message.session_id != self.state.session_id:
            raise RealtimeProtocolError("session_mismatch", "sessionId 与连接不匹配")
        kind = MessageType(message.type)
        if kind is MessageType.PING:
            await self._emit("pong", request_id=message.request_id, nonce=message.request_id)
        elif kind is MessageType.PONG:
            self.state.mark_pong()
        elif kind is MessageType.TEXT:
            await self._text(message)
        elif kind is MessageType.INTERRUPT:
            await self._interrupt(message)
        elif kind is MessageType.AUDIO_START:
            await self._audio_start(message)
        elif kind is MessageType.AUDIO_END:
            await self._audio_end(message)
        elif kind is MessageType.SPEECH_END:
            await self._clear_audio(reason=message.reason or "client_cancelled")
            await self._emit("ack", request_id=message.request_id, action=kind.value, accepted=True)
        elif kind is MessageType.SPEECH_START:
            await self._emit("ack", request_id=message.request_id, action=kind.value, accepted=True)
        elif kind is MessageType.CLOSE:
            await self._emit("ack", request_id=message.request_id, action="close", accepted=True)
            self.stop_event.set()

    async def _emit(self, event_type: str, *, request_id: str | None = None, session_id: str | None = None, run_id: str | None = None, utterance_id: str | None = None, revision: int | None = None, guard_run_id: str | None = None, **fields: Any) -> None:
        async with self._emit_lock:
            payload = event_payload(
                event_type,
                request_id=request_id,
                session_id=session_id or self.state.session_id,
                run_id=run_id,
                utterance_id=utterance_id,
                revision=revision,
                seq=self.state.next_seq(),
                **fields,
            )
            if guard_run_id:
                payload["_guardRunId"] = guard_run_id
            try:
                enqueued = await self.queue.put(payload)
                self.telemetry.observe(
                    payload,
                    enqueued=enqueued,
                    queue_depth=self.queue.qsize(),
                )
            except RealtimeBackpressureError:
                # A full critical queue cannot be made safe by waiting in the
                # receive loop. Stop the socket and let shutdown release all
                # graph/provider tasks rather than growing memory.
                self.stop_event.set()
                self._close_code = 1013
                if self._accepted:
                    try:
                        await self.websocket.close(code=1013, reason="backpressure")
                    except Exception:
                        pass
                raise

    async def _send_error(
        self, code: str, message: str, *, request_id: str | None = None, close: bool = False
    ) -> None:
        try:
            await self._emit("error", request_id=request_id, code=code, message=message)
        except Exception:
            pass
        if close:
            self.stop_event.set()
            self._close_code = _close_code(code)
            if self._accepted and (self._close_task is None or self._close_task.done()):
                self._close_task = asyncio.create_task(self._close_transport())

    async def _queue_binary(self, data: bytes, *, guard_run_id: str | None = None) -> None:
        if guard_run_id and not await self.state.owns_run(guard_run_id):
            return
        try:
            await self.queue.put(data)
        except RealtimeBackpressureError:
            self.stop_event.set()
            self._close_code = 1013
            raise

    async def _close_transport(self) -> None:
        await asyncio.sleep(0)
        try:
            await self.websocket.close(code=self._close_code)
        except Exception:
            pass

def _error_code(exc: Exception) -> str:
    return getattr(exc, "code", "session_rejected")


def _error_message(exc: Exception) -> str:
    return getattr(exc, "message", safe_error(exc))


def _close_code(error_code: str) -> int:
    return {
        "frame_too_large": 1009,
        "handshake_timeout": 4008,
        "idle_timeout": 4008,
        "backpressure": 1013,
    }.get(error_code, 1002)


def _request_id(raw: str) -> str | None:
    try:
        value = parse_control(raw).request_id
    except Exception:
        return None
    return value


__all__ = ["RealtimeConnection"]
