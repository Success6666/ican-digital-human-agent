"""Shared implementation for configuration-only provider adapters."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
from uuid import uuid4

from ..errors import ProviderNotConfiguredError, ProviderSessionError
from ...domain.models import AvatarCapabilities, AvatarHealth, AvatarSession, ProviderResult


class ConfigProvider:
    """A safe provider skeleton with no vendor SDK or secret leakage.

    Concrete adapters override only capabilities and operation labels. Real SDK
    calls can be added behind this boundary once credentials and contracts are
    available; the rest of the agent remains unchanged.
    """

    name = "provider"
    capability_defaults = AvatarCapabilities()
    required_env: tuple[str, ...] = ()
    feature_hint = "external provider adapter is disabled"

    def __init__(self, *, enabled: bool = False, ttl_seconds: int = 1800) -> None:
        self.enabled = enabled
        self.ttl_seconds = ttl_seconds
        self._sessions: set[str] = set()

    async def capabilities(self) -> AvatarCapabilities:
        return self.capability_defaults.model_copy(deep=True)

    def _configured(self) -> bool:
        return self.enabled and all(os.getenv(key) for key in self.required_env)

    async def health(self) -> AvatarHealth:
        missing = [key for key in self.required_env if not os.getenv(key)]
        if self._configured():
            return AvatarHealth(provider=self.name, status="ready", configured=True, detail="adapter enabled")
        detail = self.feature_hint
        if missing:
            detail = f"missing configuration: {', '.join(missing)}"
        return AvatarHealth(provider=self.name, status="unavailable", configured=False, detail=detail)

    async def create_session(self, user_id: str) -> AvatarSession:
        self._ensure_configured()
        now = datetime.now(UTC)
        session_id = f"{self.name}-{uuid4().hex}"
        self._sessions.add(session_id)
        return AvatarSession(
            session_id=session_id,
            provider=self.name,
            user_id=user_id,
            capabilities=await self.capabilities(),
            created_at=now,
            expires_at=now + timedelta(seconds=self.ttl_seconds),
            client_params={},
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
        raise ProviderNotConfiguredError(f"{self.name} text operation is not enabled in v0.1.2")

    async def interrupt(self, session_id: str, *, run_id: str | None = None) -> ProviderResult:
        self._ensure_session(session_id)
        return ProviderResult(
            provider=self.name,
            status="interrupted",
            metadata={"operation": "interrupt", "runId": run_id},
        )

    async def close_session(self, session_id: str) -> ProviderResult:
        self._sessions.discard(session_id)
        return ProviderResult(provider=self.name, status="closed", metadata={"operation": "close"})

    def _ensure_configured(self) -> None:
        if not self._configured():
            detail = self.feature_hint
            missing = [key for key in self.required_env if not os.getenv(key)]
            if missing:
                detail = f"missing configuration: {', '.join(missing)}"
            raise ProviderNotConfiguredError(f"{self.name}: {detail}")

    def _ensure_session(self, session_id: str) -> None:
        if session_id not in self._sessions:
            raise ProviderSessionError(f"unknown {self.name} session")
