"""Mofa Xingyun adapter skeleton for server-side long-connection proxying."""

from ...domain.models import AvatarCapabilities
from .base import ConfigProvider


class MofaProvider(ConfigProvider):
    name = "mofa"
    required_env = ()
    capability_defaults = AvatarCapabilities(text_input=True, interrupt=True, streaming=True, video_output=True)
    feature_hint = "configure MOFA_APP_ID/MOFA_APP_SECRET and MOFA_AVATAR_ENABLED=true before enabling"

    def _configured(self) -> bool:
        import os

        has_credentials = bool(os.getenv("MOFA_APP_ID") and os.getenv("MOFA_APP_SECRET"))
        return self.enabled and (bool(os.getenv("MOFA_GATEWAY_URL")) or has_credentials)
