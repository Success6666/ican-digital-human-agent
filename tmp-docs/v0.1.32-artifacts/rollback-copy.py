"""Connection/run state and bounded outbound buffering for realtime sessions."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import time
from typing import Any
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class RunBinding:
    run_id: str
    utterance_id: str
    revision: int


@dataclass(slots=True)
class _UtteranceRevision:
    revision: int
    finalized: bool = False


@dataclass(slots=True)
class ConnectionState:
    """Mutable state shared by the receive loop and run tasks."""

    connection_id: str = field(default_factory=lambda: f"conn-{uuid4().hex}")
    user_id: str | None = None
    user_name: str | None = None
    session_id: str | None = None
    hello_received: bool = False
    closed: bool = False
    sequence: int = 0
    last_activity: float = field(default_factory=time.monotonic)
    last_pong: float = field(default_factory=time.monotonic)
    active_run: RunBinding | None = None
    active_audio: tuple[str, int] | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _revisions: dict[str, _UtteranceRevision] = field(default_factory=dict, repr=False)

    async def bind(self, *, user_id: str, user_name: str, session_id: str) -> None:
        async with self._lock:
            self.user_id = user_id
            self.user_name = user_name
            self.session_id = session_id
            self.hello_received = True
            self.touch()

    def touch(self) -> None:
        self.last_activity = time.monotonic()

    def mark_pong(self) -> None:
        self.last_pong = time.monotonic()
        self.touch()

    def next_seq(self) -> int:
        self.sequence += 1
        return self.sequence

    async def accept_revision(
        self,
        utterance_id: str,
        revision: int,
        *,
        is_final: bool = False,
        allow_open_update: bool = False,
    ) -> bool:
        """Accept an interim update, or finalize one open revision.

        Clients commonly stream several interim updates and then send the
        final text with the same utterance/revision.  Text handlers opt into
        that open-revision update path; audio/control callers remain strictly
        monotonic by default.  A finalized revision is immutable, while a
        newer revision may still supersede it for corrections.
        """

        async with self._lock:
            current = self._revisions.get(utterance_id)
            if current is not None and revision < current.revision:
                return False
            if current is not None and revision == current.revision:
                if current.finalized or (not is_final and not allow_open_update):
                    return False
                current.finalized = is_final
            else:
                self._revisions[utterance_id] = _UtteranceRevision(
                    revision=revision,
                    finalized=is_final,
                )
            while len(self._revisions) > 1024:
                self._revisions.pop(next(iter(self._revisions)))
            self.touch()
            return True

    async def begin_run(self, binding: RunBinding) -> RunBinding | None:
        async with self._lock:
            previous = self.active_run
            self.active_run = binding
            self.touch()
            return previous

    async def current(self, binding: RunBinding | None = None) -> bool:
        async with self._lock:
            if self.closed or self.active_run is None:
                return False
            if binding is None:
                return True
            return self.active_run == binding

    async def owns_run(self, run_id: str) -> bool:
        """Return whether one run is still the connection's active generation."""

        async with self._lock:
            return not self.closed and self.active_run is not None and self.active_run.run_id == run_id

    async def binding(self) -> RunBinding | None:
        """Return a snapshot of the currently active run binding."""

        async with self._lock:
            return self.active_run

    async def finish_run(self, run_id: str) -> bool:
        async with self._lock:
            if self.active_run is None or self.active_run.run_id != run_id:
                return False
            self.active_run = None
            self.touch()
            return True

    async def invalidate(self, run_id: str | None = None) -> RunBinding | None:
        async with self._lock:
            current = self.active_run
            if current is None or (run_id is not None and current.run_id != run_id):
                return None
            self.active_run = None
            self.touch()
            return current

    async def start_audio(self, utterance_id: str, revision: int) -> None:
        async with self._lock:
            self.active_audio = (utterance_id, revision)
            self.touch()

    async def audio_matches(self, utterance_id: str | None = None, revision: int | None = None) -> bool:
        async with self._lock:
            if self.active_audio is None:
                return False
            current_id, current_revision = self.active_audio
            return (utterance_id is None or current_id == utterance_id) and (
                revision is None or current_revision == revision
            )

    async def finish_audio(self) -> tuple[str, int] | None:
        async with self._lock:
            current = self.active_audio
            self.active_audio = None
            self.touch()
            return current

    async def close(self) -> None:
        async with self._lock:
            self.closed = True
            self.active_run = None
            self.active_audio = None
            self._revisions.clear()
            self.touch()


class RealtimeBackpressureError(RuntimeError):
    """A critical event could not fit in the bounded outbound queue."""


class BoundedOutboundQueue:
    """Single-writer queue that drops stale low-priority events first."""

    _DROPPABLE = frozenset({"delta", "audio_queue", "transcript_partial", "filler"})

    def __init__(self, maxsize: int = 128) -> None:
        if maxsize < 1:
            raise ValueError("maxsize must be positive")
        self.maxsize = maxsize
        self._items: list[dict[str, Any] | bytes] = []
        self._condition = asyncio.Condition()
        self._closed = False
        self.dropped = 0

    async def put(self, item: dict[str, Any] | bytes) -> bool:
        event_type = str(item.get("type", "") if isinstance(item, dict) else "")
        droppable = isinstance(item, dict) and (
            event_type in self._DROPPABLE
            or (event_type == "transcript" and item.get("status") == "partial")
        )
        async with self._condition:
            if self._closed:
                return False
            if len(self._items) >= self.maxsize:
                if droppable:
                    self.dropped += 1
                    return False
                index = self._find_droppable()
                if index is None:
                    raise RealtimeBackpressureError("实时发送队列已满")
                self._items.pop(index)
                self.dropped += 1
            self._items.append(item)
            self._condition.notify()
            return True

    async def get(self) -> dict[str, Any] | bytes | None:
        async with self._condition:
            while not self._items and not self._closed:
                await self._condition.wait()
            if self._items:
                return self._items.pop(0)
            return None

    async def close(self) -> None:
        async with self._condition:
            self._closed = True
            self._condition.notify_all()

    async def drain(self) -> list[dict[str, Any] | bytes]:
        async with self._condition:
            values = list(self._items)
            self._items.clear()
            return values

    def qsize(self) -> int:
        return len(self._items)

    def _find_droppable(self) -> int | None:
        for index, item in enumerate(self._items):
            if isinstance(item, dict) and (
                str(item.get("type", "")) in self._DROPPABLE
                or (item.get("type") == "transcript" and item.get("status") == "partial")
            ):
                return index
        return None


__all__ = [
    "BoundedOutboundQueue",
    "ConnectionState",
    "RealtimeBackpressureError",
    "RunBinding",
]
