"""Mofa Xingyun browser-runtime adapter."""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from ...domain.models import AvatarCapabilities, AvatarSession, ProviderResult
from .base import ConfigProvider


class MofaProvider(ConfigProvider):
    name = "mofa"
    required_env = ()
    capability_defaults = AvatarCapabilities(
        text_input=True,
        audio_input=True,
        interrupt=True,
        interrupt_scope="run",
        streaming=True,
        video_output=True,
        external_runtime=True,
    )
    feature_hint = "configure MOFA_APP_ID/MOFA_APP_SECRET and MOFA_AVATAR_ENABLED=true before enabling"

    def _configured(self) -> bool:
        has_credentials = bool(os.getenv("MOFA_APP_ID") and os.getenv("MOFA_APP_SECRET"))
        return self.enabled and has_credentials

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
            client_params={
                "runtime": "mofa-web-sdk",
                "sdkUrl": _env_or(
                    "MOFA_SDK_URL",
                    "https://media.xingyun3d.com/xingyun3d/general/litesdk/xmovAvatar@latest.js",
                ),
                "cryptoUrl": _env_or(
                    "MOFA_CRYPTO_URL",
                    "https://cdnjs.cloudflare.com/ajax/libs/crypto-js/4.1.1/crypto-js.min.js",
                ),
                "gatewayServer": _env_or(
                    "MOFA_GATEWAY_URL",
                    "https://nebula-agent.xingyun3d.com/user/v1/ttsa/session",
                ),
                "appId": os.environ["MOFA_APP_ID"],
                "appSecret": os.environ["MOFA_APP_SECRET"],
                "emotionEnabled": _env_bool("MOFA_EMOTION_ENABLED"),
                **_optional_browser_context(),
            },
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
        return ProviderResult(
            provider=self.name,
            text=text,
            status="client_pending",
            metadata={
                "delivery": "browser-runtime",
                "mode": mode,
                "runId": run_id,
            },
        )


def _browser_user_id(user_id: str) -> str:
    digest = hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:24]
    return f"dh-{digest}"


def _env_or(name: str, default: str) -> str:
    return os.getenv(name, "").strip() or default


def _env_bool(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _optional_browser_context() -> dict[str, str]:
    """Only add vendor-specific query/header context when explicitly configured."""
    result: dict[str, str] = {}
    authorization = os.getenv("MOFA_AUTHORIZATION", "").strip()
    if authorization:
        result["authorization"] = authorization
    return result
