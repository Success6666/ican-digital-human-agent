"""iFlytek text-drive/interruption adapter skeleton."""

from ...domain.models import AvatarCapabilities
from .base import ConfigProvider


class IflytekProvider(ConfigProvider):
    name = "iflytek"
    required_env = ("IFLYTEK_APP_ID", "IFLYTEK_API_KEY", "IFLYTEK_API_SECRET")
    capability_defaults = AvatarCapabilities(text_input=True, interrupt=True, streaming=True, video_output=True)
    feature_hint = "configure iFlytek application credentials and enable the adapter"
