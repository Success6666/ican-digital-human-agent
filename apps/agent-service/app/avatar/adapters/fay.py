"""Fay external-runtime adapter; it never starts a local Fay process."""

from ...domain.models import AvatarCapabilities
from .base import ConfigProvider


class FayProvider(ConfigProvider):
    name = "fay"
    required_env = ("FAY_BASE_URL",)
    capability_defaults = AvatarCapabilities(text_input=True, interrupt=True, streaming=True, external_runtime=True)
    feature_hint = "set FAY_BASE_URL and FAY_ENABLED=true for an external Fay runtime"
