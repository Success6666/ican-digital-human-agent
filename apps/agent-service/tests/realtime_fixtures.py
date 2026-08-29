from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

from app.agent.models import IntentDecision, IntentName, IntentSource
from app.avatar.adapters.mock import MockProvider
from app.domain.models import AvatarCapabilities, AvatarSession, ProviderResult, ToolCallRecord
from app.rag.models import SearchRequest, SearchResult


class RecordingProvider(MockProvider):
    def __init__(self) -> None:
        super().__init__(ttl_seconds=60)
        self.interrupt_calls: list[str | None] = []

    async def interrupt(self, session_id: str, *, run_id: str | None = None) -> ProviderResult:
        self.interrupt_calls.append(run_id)
        return await super().interrupt(session_id, run_id=run_id)


class SlowProvider(MockProvider):
    def __init__(self) -> None:
        super().__init__(ttl_seconds=60)
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def send_text(
        self,
        session_id: str,
        text: str,
        *,
        mode: str = "text",
        run_id: str | None = None,
    ) -> ProviderResult:
        self._ensure_session(session_id)
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        return ProviderResult(provider=self.name, text=text, metadata={"runId": run_id, "mode": mode})


class SlowCloseProvider(MockProvider):
    def __init__(self) -> None:
        super().__init__(ttl_seconds=60)
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.store: Any | None = None
        self.run_id: str | None = None
        self.observed_interrupted: list[bool] = []

    async def close_session(self, session_id: str) -> ProviderResult:
        if self.store is not None:
            self.observed_interrupted.append(await self.store.is_interrupted(session_id, self.run_id))
        self.started.set()
        await self.release.wait()
        return await super().close_session(session_id)


class BlockingClassifier:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def classify(self, message: str, *, context: object | None = None) -> IntentDecision:
        del message, context
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        raise AssertionError("classifier should remain blocked in this test")


class SlowRag:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def search(self, request: SearchRequest, *, owner_id: str) -> SearchResult:
        del request, owner_id
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        raise AssertionError("RAG search should remain blocked in this test")


class SlowToolClient:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = 0

    async def call(self, name: str, arguments: dict[str, object] | None = None) -> ToolCallRecord:
        del name, arguments
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        raise AssertionError("MCP call should remain blocked in this test")


class KnowledgeClassifier:
    async def classify(self, message: str, *, context: object | None = None) -> IntentDecision:
        del message, context
        return IntentDecision(name=IntentName.KNOWLEDGE, confidence=0.9, source=IntentSource.RULE)


def session(session_id: str, now: datetime) -> AvatarSession:
    return AvatarSession(
        session_id=session_id,
        provider="mock",
        user_id="u1",
        capabilities=AvatarCapabilities(),
        created_at=now,
        expires_at=now + timedelta(seconds=60),
    )
