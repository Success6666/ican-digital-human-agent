from __future__ import annotations

import asyncio

from starlette.testclient import TestClient

from app.main import app
from app.server import create_server
from app.settings import Settings


def test_health_and_internal_token() -> None:
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/mcp").status_code == 401
        assert client.get("/mcp", headers={"X-Internal-Token": "dev-internal-token"}).status_code == 400


def test_tools_registered() -> None:
    server = create_server(Settings(internal_token="x"))

    async def check() -> list[str]:
        tools = await server.list_tools()
        return [tool.name for tool in tools]

    names = asyncio.run(check())
    assert {"echo", "system_status"}.issubset(names)
