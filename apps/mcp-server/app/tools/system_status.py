"""System status probe tool."""

from __future__ import annotations

from datetime import UTC, datetime


def register(server) -> None:
    async def system_status() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "mcp-server",
            "checked_at": datetime.now(UTC).isoformat(),
        }

    server.add_tool(
        system_status,
        name="system_status",
        title="System status",
        description="Return MCP service liveness information.",
        structured_output=True,
    )
