from __future__ import annotations

import asyncio

import pytest
from starlette.testclient import TestClient

from app.main import app
from app.server import create_server
from app.settings import Settings


def test_health_and_internal_token() -> None:
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/mcp").status_code == 401
        assert client.get("/mcp", headers={"X-Internal-Token": "dev-internal-token"}).status_code == 400


def test_production_rejects_default_internal_token() -> None:
    with pytest.raises(ValueError, match="MCP_INTERNAL_TOKEN"):
        Settings(environment="production")


@pytest.mark.parametrize(
    "token",
    [
        "replace-with-a-long-random-token",
        "replace-with-a-different-long-random-token",
        "x" * 31,
    ],
)
def test_production_rejects_public_or_short_internal_tokens(token: str) -> None:
    with pytest.raises(ValueError, match="MCP_INTERNAL_TOKEN"):
        Settings(environment="production", internal_token=token)


def test_tools_registered() -> None:
    server = create_server(Settings(internal_token="x"))

    async def check() -> list[str]:
        tools = await server.list_tools()
        return [tool.name for tool in tools]

    names = asyncio.run(check())
    assert {"echo", "system_status"}.issubset(names)
