"""MCP 2.x server factory and Streamable HTTP application."""

from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.requests import Request

from mcp.server.mcpserver import MCPServer

from .auth import InternalTokenMiddleware
from .settings import Settings, get_settings
from .tools import register_all


def create_server(settings: Settings | None = None) -> MCPServer:
    settings = settings or get_settings()
    server = MCPServer(
        name=settings.service_name,
        version="0.1.8",
        instructions="Deterministic chain-probe tools for the digital human agent.",
        debug=False,
    )
    register_all(server)

    @server.custom_route("/health", methods=["GET"], include_in_schema=False)
    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "service": settings.service_name, "version": "0.1.8"})

    @server.custom_route("/ready", methods=["GET"], include_in_schema=False)
    async def ready(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ready", "service": settings.service_name})

    return server


def create_app(settings: Settings | None = None):
    settings = settings or get_settings()
    server = create_server(settings)
    mcp_app = server.streamable_http_app(
        streamable_http_path=settings.streamable_http_path,
        stateless_http=settings.stateless_http,
        json_response=False,
        max_request_body_size=settings.max_request_body_size,
        host=settings.host,
    )
    # The MCP SDK returns a Starlette app with its own lifespan/session manager.
    # Wrapping it preserves that lifecycle while enforcing our internal token.
    mcp_app.add_middleware(InternalTokenMiddleware, expected_token=settings.internal_token)
    return mcp_app
