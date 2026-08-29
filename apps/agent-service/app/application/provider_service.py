"""Provider discovery use cases."""

from ..avatar.registry import ProviderRegistry


class ProviderApplicationService:
    def __init__(self, registry: ProviderRegistry) -> None:
        self.registry = registry

    async def list(self):
        return await self.registry.health()
