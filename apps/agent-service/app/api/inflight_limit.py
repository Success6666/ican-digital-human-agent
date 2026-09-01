"""Bounded request admission for predictable memory and queue usage."""

from __future__ import annotations

import asyncio

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class InFlightLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, limit: int = 4096) -> None:
        super().__init__(app)
        self._limit = max(1, int(limit))
        self._count = 0
        self._lock = asyncio.Lock()

    async def dispatch(self, request: Request, call_next):
        async with self._lock:
            if self._count >= self._limit:
                return JSONResponse({"detail": "agent concurrency capacity reached"}, status_code=503, headers={"Retry-After": "1"})
            self._count += 1
        try:
            return await call_next(request)
        finally:
            async with self._lock:
                self._count = max(0, self._count - 1)
