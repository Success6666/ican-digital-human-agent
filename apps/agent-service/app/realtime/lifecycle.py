"""Writer, heartbeat and shutdown lifecycle for a realtime socket."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
import time
from typing import Any


class RealtimeLifecycleMixin:
    async def _writer(self) -> None:
        while True:
            item = await self.queue.get()
            if item is None:
                return
            if isinstance(item, bytes):
                binding = await self.state.binding()
                self.telemetry.binary_output(
                    len(item), run_id=binding.run_id if binding is not None else None
                )
                try:
                    await self.websocket.send_bytes(item)
                except Exception:
                    self._writer_failed = True
                    self.stop_event.set()
                    self._close_code = 1011
                    try:
                        await self.websocket.close(code=1011, reason="realtime writer failed")
                    except Exception:
                        pass
                    return
                continue
            if not await self._allow(item):
                continue
            item.pop("_guardRunId", None)
            try:
                await self.websocket.send_json(item)
            except Exception:
                self._writer_failed = True
                self.stop_event.set()
                self._close_code = 1011
                try:
                    await self.websocket.close(code=1011, reason="realtime writer failed")
                except Exception:
                    pass
                return

    async def _allow(self, item: dict[str, Any]) -> bool:
        run_id = item.get("_guardRunId")
        if not run_id:
            return True
        event_type = str(item.get("type", ""))
        if run_id in self.cancelled_runs:
            return event_type in {"interrupted", "run_done", "ack"}
        if run_id in self.completed_runs:
            return True
        return await self.state.owns_run(str(run_id))

    def _remember_run(self, bucket: set[str], run_id: str) -> None:
        bucket.add(run_id)
        while len(bucket) > 512:
            bucket.pop()

    async def _heartbeat(self) -> None:
        while not self.stop_event.is_set():
            await asyncio.sleep(self.limits.heartbeat_interval_seconds)
            if self.stop_event.is_set():
                return
            if time.monotonic() - max(self.state.last_activity, self.state.last_pong) > self.limits.idle_timeout_seconds:
                await self._send_error("idle_timeout", "连接空闲超时", close=True)
                return
            if not await self._renew_session_lease():
                return
            await self._emit("ping", heartbeat=True, timestamp=time.time())

    async def _renew_session_lease(self) -> bool:
        """Keep the HTTP session lease aligned with a live realtime socket."""

        session_id = self.state.session_id
        heartbeat = getattr(self.container, "store", None)
        heartbeat = getattr(heartbeat, "heartbeat", None)
        if not session_id or not callable(heartbeat):
            return True
        binding = await self.state.binding()
        run_id = binding.run_id if binding is not None else None
        try:
            accepted = await heartbeat(session_id, run_id)
        except Exception:
            # A telemetry/lease backend outage must not tear down an otherwise
            # usable connection; the next request will surface the real state.
            return True
        if accepted:
            return True
        # A correction can replace the binding while the heartbeat for the
        # previous run is in flight. Never close the socket based on that
        # stale rejection; the next heartbeat will renew the new generation.
        latest = await self.state.binding()
        if latest != binding:
            return True
        code = "run_superseded" if binding is not None else "session_expired"
        message = "当前运行已被新的请求接管" if binding is not None else "会话已过期，请重新建立会话"
        await self._send_error(code, message, close=True)
        return False

    def _schedule(self, awaitable: Awaitable[Any]) -> None:
        task = asyncio.create_task(awaitable)
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)

    async def _shutdown(self) -> None:
        self.stop_event.set()
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
        active = await self.state.invalidate()
        if active is not None:
            self._remember_run(self.cancelled_runs, active.run_id)
            try:
                await self.container.session_service.mark_run_interrupted(
                    session_id=self.state.session_id or "", run_id=active.run_id,
                )
            except Exception:
                pass
        for task in list(self.run_tasks.values()):
            task.cancel()
        for task in list(self.background_tasks):
            task.cancel()
        await asyncio.gather(*self.run_tasks.values(), *self.background_tasks, return_exceptions=True)
        if self._close_task is not None:
            await asyncio.gather(self._close_task, return_exceptions=True)
        await self.ingress.reset()
        await self.state.close()
        await self.queue.close()
        if self._writer_task is not None:
            await self._writer_task
        if self._accepted:
            try:
                await self.websocket.close(code=self._close_code)
            except Exception:
                pass
        self.telemetry.closed(code=self._close_code)


__all__ = ["RealtimeLifecycleMixin"]
