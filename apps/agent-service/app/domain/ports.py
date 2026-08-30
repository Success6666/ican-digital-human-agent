"""Ports used by application services.

Adapters implement these protocols; the graph and HTTP layer depend only on
these contracts, which keeps provider SDK details out of orchestration code.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from .models import (
    AvatarCapabilities,
    AvatarHealth,
    AvatarSession,
    ProviderResult,
    SessionRecord,
    ToolCallRecord,
)


class AvatarProvider(Protocol):
    name: str

    async def capabilities(self) -> AvatarCapabilities: ...

    async def create_session(self, user_id: str) -> AvatarSession: ...

    async def send_text(
        self,
        session_id: str,
        text: str,
        *,
        mode: str = "text",
        run_id: str | None = None,
    ) -> ProviderResult: ...

    async def interrupt(self, session_id: str, *, run_id: str | None = None) -> ProviderResult: ...

    async def close_session(self, session_id: str) -> ProviderResult: ...

    async def health(self) -> AvatarHealth: ...


class ToolClient(Protocol):
    async def call(self, name: str, arguments: dict[str, Any] | None = None) -> ToolCallRecord: ...


class SessionCapacityError(RuntimeError):
    """Raised when a session store has no capacity for a new session."""


class SessionStore(Protocol):
    async def create(self, session: AvatarSession) -> None: ...

    async def claim_expired_cleanup(self, session_id: str, generation_id: str | None) -> bool: ...

    async def finish_expired_cleanup(self, session_id: str, generation_id: str | None) -> None: ...

    async def requeue_expired(self, record: SessionRecord) -> bool: ...

    async def get(self, session_id: str) -> SessionRecord | None: ...

    async def touch(
        self,
        session_id: str,
        now: datetime | None = None,
        *,
        clear_interrupt: bool = False,
        run_id: str | None = None,
    ) -> bool: ...

    async def begin_run(self, session_id: str, run_id: str | None = None) -> str | None: ...

    async def heartbeat(
        self,
        session_id: str,
        run_id: str | None = None,
        now: datetime | None = None,
    ) -> bool: ...

    async def is_interrupted(self, session_id: str, run_id: str | None = None) -> bool: ...

    async def wait_for_stop(self, session_id: str, run_id: str) -> None: ...

    async def mark_interrupted(self, session_id: str, run_id: str | None = None) -> SessionRecord | None: ...

    async def close(self, session_id: str) -> SessionRecord | None: ...

    async def remove_expired(
        self,
        now: datetime | None = None,
        *,
        limit: int | None = None,
    ) -> list[SessionRecord]: ...

    async def list_for_user(self, user_id: str, *, limit: int = 100) -> list[SessionRecord]: ...

    async def size(self) -> int: ...

    async def stats(self) -> dict[str, int]: ...
