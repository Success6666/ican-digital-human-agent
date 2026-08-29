"""Alibaba Cloud digital-human adapter skeleton.

Only server-side configuration and short-lived session shape are exposed. No
AK/SK is returned to callers and no vendor SDK is imported in v0.1.0.
"""

from ...domain.models import AvatarCapabilities
from .base import ConfigProvider


class AliyunProvider(ConfigProvider):
    name = "aliyun"
    required_env = ("ALIYUN_AVATAR_ACCESS_KEY_ID", "ALIYUN_AVATAR_ACCESS_KEY_SECRET")
    capability_defaults = AvatarCapabilities(text_input=True, interrupt=True, streaming=True, video_output=True)
    feature_hint = "set ALIYUN_AVATAR_ENABLED=true to enable the server-side adapter"
