"""MCP tool domains."""

from .echo import register as register_echo
from .system_status import register as register_system_status


def register_all(server) -> None:
    register_echo(server)
    register_system_status(server)
