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

    async def send_text(self, session_id: str, text: str, *, mode: str = "text") -> ProviderResult: ...

    async def interrupt(self, session_id: str) -> ProviderResult: ...

    async def close_session(self, session_id: str) -> ProviderResult: ...

    async def health(self) -> AvatarHealth: ...


class ToolClient(Protocol):
    async def call(self, name: str, arguments: dict[str, Any] | None = None) -> ToolCallRecord: ...


class SessionStore(Protocol):
    async def create(self, session: AvatarSession) -> None: ...

    async def get(self, session_id: str) -> SessionRecord | None: ...

    async def touch(self, session_id: str, now: datetime | None = None, *, clear_interrupt: bool = False) -> None: ...

    async def begin_run(self, session_id: str) -> str | None: ...

    async def is_interrupted(self, session_id: str, run_id: str | None = None) -> bool: ...

    async def mark_interrupted(self, session_id: str, run_id: str | None = None) -> SessionRecord | None: ...

    async def close(self, session_id: str) -> SessionRecord | None: ...

    async def remove_expired(self, now: datetime) -> list[SessionRecord]: ...

    async def list_for_user(self, user_id: str) -> list[SessionRecord]: ...
