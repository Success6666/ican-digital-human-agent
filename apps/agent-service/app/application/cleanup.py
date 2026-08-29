"""Background session cleanup task with explicit cancellation."""

from __future__ import annotations

import asyncio
import logging

from .session_service import SessionApplicationService

logger = logging.getLogger(__name__)


class CleanupWorker:
    def __init__(self, service: SessionApplicationService, *, interval_seconds: int = 30) -> None:
        self.service = service
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="agent-session-cleanup")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _run(self) -> None:
        while True:
            try:
                await asyncio.sleep(self.interval_seconds)
                await self.service.cleanup_expired()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("session cleanup failed")
