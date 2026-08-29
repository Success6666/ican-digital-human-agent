"""Telemetry sink port."""

from __future__ import annotations

from typing import Protocol

from .models import TelemetryEvent


class EventSink(Protocol):
    async def emit(self, event: TelemetryEvent) -> None: ...

    async def flush(self) -> None: ...
