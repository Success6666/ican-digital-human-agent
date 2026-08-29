"""Echo probe tool."""

from __future__ import annotations


def register(server) -> None:
    async def echo(message: str) -> dict[str, str]:
        return {"echo": message}

    server.add_tool(
        echo,
        name="echo",
        title="Echo",
        description="Return the supplied message as a deterministic MCP probe.",
        structured_output=True,
    )
