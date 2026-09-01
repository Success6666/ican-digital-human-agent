"""Message handlers for the realtime connection.

The mixin keeps transport orchestration separate from text/audio lifecycle
logic.  It intentionally relies on the small attribute contract supplied by
``RealtimeConnection`` instead of importing the concrete class.
"""

from __future__ import annotations

import asyncio
import inspect
from uuid import uuid4

from ..graph.runtime_support import safe_error
from .audio_handlers import RealtimeAudioHandlersMixin
from .protocol import (
    RealtimeMessage,
    agent_event_payload,
    require_text,
)
from .state import RunBinding


class RealtimeHandlersMixin(RealtimeAudioHandlersMixin):
    async def _text(self, message: RealtimeMessage) -> None:
        require_text(message)
        utterance_id = message.utterance_id or f"utt-{uuid4().hex}"
        revision = message.revision or 1
        if not message.is_final:
            accepted = await self.state.accept_revision(
                utterance_id,
                revision,
                is_final=False,
                allow_open_update=True,
            )
            ticket = None
        else:
            ticket = await self.state.reserve_revision(
                utterance_id,
                revision,
                is_final=True,
                allow_open_update=True,
            )
            accepted = ticket is not None
        if not accepted:
            await self._emit(
                "ack", request_id=message.request_id, action="text", accepted=False,
                reason="stale_revision", utterance_id=utterance_id, revision=revision,
            )
            return
        if not message.is_final:
            await self._emit(
                "transcript", request_id=message.request_id, utterance_id=utterance_id,
                revision=revision, status="partial", source="client", text=message.text,
            )
            await self._emit(
                "ack", request_id=message.request_id, action="text", accepted=True,
                final=False, utterance_id=utterance_id, revision=revision,
            )
            return
        committed = False
        try:
            await self._clear_audio(reason="text_started")
            old = await self._stop_active()
            if old is not None:
                await self._publish_interrupted(old, reason="superseded")
            await asyncio.sleep(0)
            if len(self.run_tasks) >= self.limits.max_pending_runs:
                await self._send_error("run_capacity", "实时运行数量已达到上限")
                return
            run_id = await self.container.session_service.begin_run(
                user_id=self.state.user_id or "", session_id=self.state.session_id or "",
            )
            if not run_id:
                await self._send_error("session_unavailable", "会话当前不可用")
                return
            committed = True
        finally:
            if not committed:
                await self.state.rollback_revision(ticket)
        binding = RunBinding(run_id=str(run_id), utterance_id=utterance_id, revision=revision)
        await self.state.begin_run(binding)
        # Register the task before the first await after ``begin_run``.  A
        # close/correction from another coroutine can otherwise invalidate the
        # binding while no task is visible to ``_stop_active``.  The gate keeps
        # ack/run_started ahead of graph output while still making the task
        # cancellable during that short handshake window.
        start_gate = asyncio.Event()
        task = asyncio.create_task(
            self._run_text(binding, message.text or "", start_gate),
            name=f"realtime-run-{binding.run_id}",
        )
        self.run_tasks[binding.run_id] = task
        try:
            if not await self.state.current(binding):
                start_gate.set()
                await asyncio.gather(task, return_exceptions=True)
                return
            await self._emit(
                "ack", request_id=message.request_id, action="text", accepted=True,
                run_id=binding.run_id, utterance_id=utterance_id, revision=revision,
            )
            if not await self.state.current(binding):
                start_gate.set()
                await asyncio.gather(task, return_exceptions=True)
                return
            await self._emit(
                "run_started", request_id=message.request_id, run_id=binding.run_id,
                utterance_id=utterance_id, revision=revision, status="running",
            )
        except BaseException:
            start_gate.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise
        start_gate.set()

    async def _run_text(
        self,
        binding: RunBinding,
        text: str,
        start_gate: asyncio.Event | None = None,
    ) -> None:
        task = asyncio.current_task()
        saw_interrupted = False
        try:
            if start_gate is not None:
                await start_gate.wait()
            events = self.container.chat_service.stream(
                user_id=self.state.user_id or "", user_name=self.state.user_name or "",
                session_id=self.state.session_id or "", message=text, run_id=binding.run_id,
            )
            events = await events if inspect.isawaitable(events) else events
            async for event in events:
                if not await self.state.current(binding):
                    return
                payload = agent_event_payload(
                    event, session_id=self.state.session_id or "", run_id=binding.run_id,
                    utterance_id=binding.utterance_id, revision=binding.revision,
                )
                if payload is None:
                    continue
                event_type = str(payload.pop("type", "message"))
                saw_interrupted = saw_interrupted or event_type == "interrupted" or bool(payload.get("interrupted"))
                for key in ("requestId", "sessionId", "runId", "utteranceId", "revision", "seq"):
                    payload.pop(key, None)
                await self._emit(
                    event_type, run_id=binding.run_id, utterance_id=binding.utterance_id,
                    revision=binding.revision, guard_run_id=binding.run_id, **payload,
                )
                if event_type == "delta" and payload.get("text"):
                    self._schedule(self._synthesize_text(str(payload["text"]), binding))
            if await self.state.current(binding):
                self._remember_run(self.completed_runs, binding.run_id)
                await self._publish_run_done(
                    binding, status="interrupted" if saw_interrupted else "ok", interrupted=saw_interrupted,
                )
                await self.state.finish_run(binding.run_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if await self.state.current(binding):
                self._remember_run(self.completed_runs, binding.run_id)
                await self._emit(
                    "error", run_id=binding.run_id, utterance_id=binding.utterance_id,
                    revision=binding.revision, guard_run_id=binding.run_id,
                    code="run_failed", message=safe_error(exc),
                )
                await self._publish_run_done(binding, status="error", interrupted=False)
                await self.state.finish_run(binding.run_id)
        finally:
            if self.run_tasks.get(binding.run_id) is task:
                self.run_tasks.pop(binding.run_id, None)

    async def _synthesize_text(self, text: str, binding: RunBinding) -> None:
        output = getattr(self, "audio_output", None)
        synthesize = getattr(output, "synthesize", None)
        if not callable(synthesize) or not getattr(output, "enabled", False):
            return
        try:
            try:
                await asyncio.wait_for(self._tts_semaphore.acquire(), timeout=0.05)
            except asyncio.TimeoutError:
                return
            try:
                chunks = synthesize(text, run_id=binding.run_id)
                async for chunk in chunks:
                    if not await self.state.current(binding):
                        return
                    if isinstance(chunk, bytes) and chunk:
                        await self._queue_binary(chunk, guard_run_id=binding.run_id)
            finally:
                self._tts_semaphore.release()
        except asyncio.CancelledError:
            raise
        except Exception:
            return

    async def _interrupt(self, message: RealtimeMessage) -> None:
        binding = await self.state.binding()
        if binding is None:
            await self._emit("ack", request_id=message.request_id, action="interrupt", accepted=False, reason="no_active_run")
            return
        mismatched = any(
            value is not None and value != expected
            for value, expected in (
                (message.run_id, binding.run_id),
                (message.utterance_id, binding.utterance_id),
                (message.revision, binding.revision),
            )
        )
        if mismatched:
            await self._emit(
                "ack", request_id=message.request_id, action="interrupt", accepted=False,
                reason="stale_run", run_id=binding.run_id, utterance_id=binding.utterance_id,
                revision=binding.revision,
            )
            return
        stopped = await self._stop_active(binding.run_id)
        await self._clear_audio(reason="interrupted")
        await self._emit(
            "ack", request_id=message.request_id, action="interrupt", accepted=stopped is not None,
            run_id=binding.run_id, utterance_id=binding.utterance_id, revision=binding.revision,
        )
        if stopped is not None:
            await self._publish_interrupted(stopped, reason=message.reason or "client_interrupt")

    async def _stop_active(self, run_id: str | None = None) -> RunBinding | None:
        binding = await self.state.invalidate(run_id)
        if binding is None:
            return None
        self._remember_run(self.cancelled_runs, binding.run_id)
        await self.container.session_service.mark_run_interrupted(
            session_id=self.state.session_id or "", run_id=binding.run_id,
        )
        task = self.run_tasks.get(binding.run_id)
        if task is not None and not task.done():
            task.cancel()
        self._schedule(self._remote_interrupt(binding))
        return binding

    async def _clear_audio(self, *, reason: str | None = None) -> None:
        current = await self.state.finish_audio()
        if current is None:
            return
        await self.ingress.reset()
        if reason:
            await self._emit(
                "audio_queue", utterance_id=current[0], revision=current[1],
                status="interrupted", frames=0, bytesReceived=0, bufferedBytes=0,
                capacityBytes=self.limits.max_audio_buffer_bytes, reason=reason,
            )

    async def _remote_interrupt(self, binding: RunBinding) -> None:
        try:
            await asyncio.wait_for(
                self.container.session_service.interrupt(
                    user_id=self.state.user_id or "", session_id=self.state.session_id or "",
                    run_id=binding.run_id,
                ),
                timeout=self.limits.interrupt_timeout_seconds,
            )
        except BaseException:
            return

    async def _publish_interrupted(self, binding: RunBinding, *, reason: str) -> None:
        if binding.run_id in self.terminal_runs:
            return
        self._remember_run(self.terminal_runs, binding.run_id)
        await self._emit(
            "interrupted", run_id=binding.run_id, utterance_id=binding.utterance_id,
            revision=binding.revision, guard_run_id=binding.run_id, reason=reason,
            message="请求已打断。",
        )
        await self._publish_run_done(binding, status="interrupted", interrupted=True)

    async def _publish_run_done(self, binding: RunBinding, *, status: str, interrupted: bool) -> None:
        await self._emit(
            "run_done", run_id=binding.run_id, utterance_id=binding.utterance_id,
            revision=binding.revision, guard_run_id=binding.run_id,
            status=status, interrupted=interrupted,
        )


__all__ = ["RealtimeHandlersMixin"]
