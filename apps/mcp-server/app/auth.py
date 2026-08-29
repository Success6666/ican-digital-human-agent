"""ASGI middleware for the internal Agent -> MCP trust boundary."""

from __future__ import annotations

import json
import secrets
from collections.abc import Awaitable, Callable
from typing import Any


class InternalTokenMiddleware:
    def __init__(self, app: Callable[..., Awaitable[Any]], expected_token: str) -> None:
        self.app = app
        self.expected_token = expected_token

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if path in {"/health", "/ready"}:
            await self.app(scope, receive, send)
            return
        headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope.get("headers", [])}
        supplied = headers.get("x-internal-token", "")
        if not self.expected_token or not secrets.compare_digest(supplied, self.expected_token):
            body = json.dumps({"detail": "unauthorized"}, ensure_ascii=False).encode("utf-8")
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)
