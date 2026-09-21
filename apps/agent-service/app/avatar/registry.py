"""Provider registry and configuration-aware factory."""

from __future__ import annotations

from collections.abc import Iterable

from ..domain.models import AvatarCapabilities, AvatarHealth
from ..domain.ports import AvatarProvider
from ..settings import Settings, get_settings
from .adapters import (
    AliyunProvider,
    FayProvider,
    IflytekProvider,
    MockProvider,
    MofaProvider,
)
from .errors import ProviderError


class ProviderRegistry:
    def __init__(self, providers: Iterable[AvatarProvider]) -> None:
        self._providers = {provider.name: provider for provider in providers}

    def get(self, name: str) -> AvatarProvider:
        try:
            return self._providers[name]
        except KeyError as exc:
            raise ProviderError(f"unsupported provider: {name}") from exc

    def names(self) -> list[str]:
        return list(self._providers)

    async def capabilities(self, name: str) -> AvatarCapabilities:
        return await self.get(name).capabilities()

    async def health(self) -> list[AvatarHealth]:
        return [await self._providers[name].health() for name in self.names()]

    def set_session_ttl(self, ttl_seconds: int) -> None:
        for provider in self._providers.values():
            if hasattr(provider, "ttl_seconds"):
                provider.ttl_seconds = ttl_seconds


def build_default_registry(settings: Settings | None = None) -> ProviderRegistry:
    settings = settings or get_settings()
    enabled = settings.provider_enabled
    return ProviderRegistry(
        [
            MockProvider(ttl_seconds=settings.session_ttl_seconds),
            AliyunProvider(enabled=enabled.get("aliyun", False), ttl_seconds=settings.session_ttl_seconds),
            MofaProvider(enabled=enabled.get("mofa", False), ttl_seconds=settings.session_ttl_seconds),
            IflytekProvider(enabled=enabled.get("iflytek", False), ttl_seconds=settings.session_ttl_seconds),
            FayProvider(enabled=enabled.get("fay", False), ttl_seconds=settings.session_ttl_seconds),
        ]
    )
