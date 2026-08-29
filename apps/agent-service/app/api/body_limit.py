"""Bound HTTP request bodies before FastAPI materializes JSON payloads."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


class RequestBodyLimitMiddleware:
    """Reject oversized request bodies at the ASGI receive boundary.

    A content-length check handles normal requests without reading the body.
    The wrapped receiver also counts chunked requests, so callers cannot avoid
    the limit by omitting the header. The middleware is intentionally transport
    agnostic and can be reused when the service moves behind another gateway.
    """

    def __init__(self, app: Callable[..., Awaitable[Any]], *, max_bytes: int) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: dict[str, Any], receive: Callable[..., Awaitable[Any]], send: Callable[..., Awaitable[Any]]) -> None:
        if scope.get("type") != "http" or scope.get("method", "GET").upper() not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                if int(raw_length) > self.max_bytes:
                    await _reject(send, self.max_bytes)
                    return
            except (TypeError, ValueError):
                # Invalid length headers are left to the server/parser; the
                # chunk counter below still protects a valid request stream.
                pass

        received = 0
        response_started = False

        async def tracked_send(message: dict[str, Any]) -> None:
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        async def limited_receive() -> dict[str, Any]:
            nonlocal received
            message = await receive()
            if message.get("type") != "http.request":
                return message
            body = message.get("body", b"") or b""
            received += len(body)
            if received > self.max_bytes:
                raise _RequestBodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, tracked_send)
        except _RequestBodyTooLarge:
            if not response_started:
                await _reject(send, self.max_bytes)


class _RequestBodyTooLarge(Exception):
    """Internal control-flow exception used to stop an oversized request."""


async def _reject(send: Callable[..., Awaitable[Any]], max_bytes: int) -> None:
    body = f'{{"detail":"request body exceeds {max_bytes} bytes"}}'.encode("ascii")
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode("ascii"))],
        }
    )
    await send({"type": "http.response.body", "body": body})


__all__ = ["RequestBodyLimitMiddleware"]
