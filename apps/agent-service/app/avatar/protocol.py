"""Public provider protocol re-export kept stable for adapter authors."""

from ..domain.models import (
    AvatarCapabilities,
    AvatarHealth,
    AvatarSession,
    ProviderResult,
)
from ..domain.ports import AvatarProvider

__all__ = ["AvatarCapabilities", "AvatarHealth", "AvatarProvider", "AvatarSession", "ProviderResult"]
