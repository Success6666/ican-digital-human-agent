"""Deterministic provider used for local and CI end-to-end checks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from ...domain.models import (
    AvatarCapabilities,
    AvatarHealth,
    AvatarSession,
    ProviderResult,
)
from ..errors import ProviderSessionError


class MockProvider:
    name = "mock"

    def __init__(self, *, ttl_seconds: int = 1800) -> None:
        self.ttl_seconds = ttl_seconds
        self._sessions: set[str] = set()

    async def capabilities(self) -> AvatarCapabilities:
        return AvatarCapabilities(
            text_input=True,
            interrupt=True,
            interrupt_scope="run",
            streaming=True,
        )

    async def health(self) -> AvatarHealth:
        return AvatarHealth(provider=self.name, status="ready", configured=True, detail="deterministic local provider")

    async def create_session(self, user_id: str) -> AvatarSession:
        now = datetime.now(UTC)
        session_id = f"mock-{uuid4().hex}"
        self._sessions.add(session_id)
        return AvatarSession(
            session_id=session_id,
            provider=self.name,
            user_id=user_id,
            capabilities=await self.capabilities(),
            created_at=now,
            expires_at=now + timedelta(seconds=self.ttl_seconds),
            client_params={"mode": "local-mock"},
        )

    async def send_text(
        self,
        session_id: str,
        text: str,
        *,
        mode: str = "text",
        run_id: str | None = None,
    ) -> ProviderResult:
        self._ensure_session(session_id)
        clean = text.strip()
        return ProviderResult(
            provider=self.name,
            text=f"Mock 数字人已收到：{clean}",
            status="ok",
            metadata={"mode": mode, "deterministic": True, "runId": run_id},
        )

    async def interrupt(self, session_id: str, *, run_id: str | None = None) -> ProviderResult:
        self._ensure_session(session_id)
        return ProviderResult(provider=self.name, status="interrupted", metadata={"runId": run_id})

    async def close_session(self, session_id: str) -> ProviderResult:
        self._sessions.discard(session_id)
        return ProviderResult(provider=self.name, status="closed")

    def _ensure_session(self, session_id: str) -> None:
        if session_id not in self._sessions:
            raise ProviderSessionError("unknown mock session")
