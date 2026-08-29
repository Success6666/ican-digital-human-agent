"""MCP 2.x Streamable HTTP client and deterministic local fallback."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
import socket
import time
from typing import Any
from urllib.parse import urlsplit

from ..domain.models import ToolCallRecord
from .limits import ToolResultLimiter


class McpClientError(RuntimeError):
    """The MCP endpoint could not execute a tool."""


class LocalToolClient:
    """In-process MCP-compatible probe for isolated development/tests.

    It mirrors the two tools exposed by ``mcp-server`` and remains behind the
    ToolClient port; graph nodes never call these functions directly.
    """

    def __init__(
        self,
        *,
        service_name: str = "mcp-server",
        result_limiter: ToolResultLimiter | None = None,
    ) -> None:
        self.service_name = service_name
        self.result_limiter = result_limiter or ToolResultLimiter()
        self._tools: dict[str, Callable[[dict[str, Any]], Awaitable[Any]]] = {
            "echo": self._echo,
            "system_status": self._system_status,
        }

    async def call(self, name: str, arguments: dict[str, Any] | None = None) -> ToolCallRecord:
        started = time.perf_counter()
        args = arguments or {}
        fn = self._tools.get(name)
        if fn is None:
            return ToolCallRecord(name=name, arguments=args, error=f"unknown MCP tool: {name}")
        try:
            result = await fn(args)
            record = ToolCallRecord(
                name=name,
                arguments=args,
                result=result,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            return self.result_limiter.limit_record(record)
        except Exception as exc:  # pragma: no cover - defensive boundary
            return ToolCallRecord(name=name, arguments=args, error=_safe_error(exc))

    async def _echo(self, arguments: dict[str, Any]) -> dict[str, Any]:
        value = arguments.get("message", "")
        return {"echo": str(value)}

    async def _system_status(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"status": "ok", "service": self.service_name, "checked_at": datetime.now(UTC).isoformat()}


class StreamableHttpToolClient:
    """Thin adapter over the official MCP 2.x Python client."""

    def __init__(
        self,
        url: str,
        *,
        internal_token: str,
        timeout_seconds: float = 10.0,
        result_limiter: ToolResultLimiter | None = None,
    ) -> None:
        self.url = url
        self.internal_token = internal_token
        self.timeout_seconds = timeout_seconds
        self.result_limiter = result_limiter or ToolResultLimiter()

    async def call(self, name: str, arguments: dict[str, Any] | None = None) -> ToolCallRecord:
        started = time.perf_counter()
        try:
            result = await asyncio.wait_for(self._call_remote(name, arguments or {}), timeout=self.timeout_seconds)
            parsed = _parse_result(result)
            parsed.name = name
            parsed.arguments = arguments or {}
            parsed.duration_ms = round((time.perf_counter() - started) * 1000, 2)
            return self.result_limiter.limit_record(parsed)
        except Exception as exc:
            return ToolCallRecord(
                name=name,
                arguments=arguments or {},
                error=_safe_error(exc),
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )

    async def _call_remote(self, name: str, arguments: dict[str, Any]) -> Any:
        try:
            import httpx
            from mcp.client.session import ClientSession
            from mcp.client.streamable_http import streamable_http_client
        except ImportError as exc:  # pragma: no cover - dependency packaging issue
            raise McpClientError("MCP 2.x client dependency is unavailable") from exc

        headers = {"X-Internal-Token": self.internal_token}
        # Keep startup responsive when the optional MCP container is down while
        # retaining a larger read budget for a real streaming tool call.
        timeout = httpx.Timeout(
            self.timeout_seconds,
            connect=min(self.timeout_seconds, 2.0),
            pool=min(self.timeout_seconds, 2.0),
        )
        async with httpx.AsyncClient(headers=headers, timeout=timeout) as http_client:
            async with streamable_http_client(self.url, http_client=http_client) as (read_stream, write_stream):
                async with ClientSession(
                    read_stream,
                    write_stream,
                    read_timeout_seconds=self.timeout_seconds,
                ) as session:
                    await session.initialize()
                    await session.list_tools()
                    return await session.call_tool(name, arguments)


class CompositeToolClient:
    """Remote MCP first, local probe fallback when explicitly allowed."""

    def __init__(
        self,
        remote: StreamableHttpToolClient,
        local: LocalToolClient,
        *,
        allow_fallback: bool = True,
        remote_budget_seconds: float | None = 0.8,
        result_limiter: ToolResultLimiter | None = None,
    ) -> None:
        self.remote = remote
        self.local = local
        self.allow_fallback = allow_fallback
        self.remote_budget_seconds = remote_budget_seconds if remote_budget_seconds and remote_budget_seconds > 0 else None
        self.result_limiter = (
            result_limiter
            or getattr(remote, "result_limiter", None)
            or getattr(local, "result_limiter", None)
            or ToolResultLimiter()
        )
        self._remote_unavailable_until = 0.0

    async def call(self, name: str, arguments: dict[str, Any] | None = None) -> ToolCallRecord:
        if self.allow_fallback and time.monotonic() < self._remote_unavailable_until:
            local_result = await self.local.call(name, arguments)
            return self._fallback_result(local_result, "MCP endpoint temporarily unavailable")
        try:
            if self.allow_fallback and self.remote_budget_seconds is not None:
                reachable = await self._tcp_probe()
                if not reachable:
                    self._remote_unavailable_until = time.monotonic() + 5.0
                    local_result = await self.local.call(name, arguments)
                    return self._fallback_result(local_result, "MCP endpoint unavailable")
            # The fast budget is only a connectivity probe. Once the endpoint
            # is reachable, retain the full MCP request timeout configured on
            # StreamableHttpToolClient so real tools are not cut off early.
            remote_result = await self.remote.call(name, arguments)
        except asyncio.TimeoutError:
            self._remote_unavailable_until = time.monotonic() + 5.0
            local_result = await self.local.call(name, arguments)
            return self._fallback_result(local_result, "MCP connectivity probe timeout")
        if not remote_result.error or not self.allow_fallback:
            return self.result_limiter.limit_record(remote_result)
        self._remote_unavailable_until = time.monotonic() + 5.0
        local_result = await self.local.call(name, arguments)
        return self._fallback_result(local_result, remote_result.error)

    def _fallback_result(self, result: ToolCallRecord, remote_error: str | None) -> ToolCallRecord:
        bounded = self.result_limiter.limit_record(result)
        return bounded.model_copy(
            update={
                "metadata": {
                    **bounded.metadata,
                    "fallback": True,
                    "remote_error": remote_error or "MCP endpoint unavailable",
                }
            }
        )

    async def _tcp_probe(self) -> bool:
        """Avoid paying MCP protocol teardown cost for a dead endpoint."""
        parsed = urlsplit(self.remote.url)
        host = parsed.hostname
        if not host:
            return False
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            _reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port, family=socket.AF_INET),
                timeout=self.remote_budget_seconds,
            )
        except (OSError, asyncio.TimeoutError, ValueError):
            return False
        writer.close()
        try:
            await writer.wait_closed()
        except (OSError, asyncio.CancelledError):
            pass
        return True


def _parse_result(result: Any) -> ToolCallRecord:
    if getattr(result, "is_error", False):
        return ToolCallRecord(name="", error="MCP tool returned an error")
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        return ToolCallRecord(name="", result=structured)
    texts = [getattr(item, "text", "") for item in getattr(result, "content", []) if getattr(item, "type", "") == "text"]
    return ToolCallRecord(name="", result="\n".join(texts))


def _safe_error(exc: Exception) -> str:
    # Do not include URLs, headers, or exception reprs that could contain secrets.
    message = str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__
    return message[:300]
