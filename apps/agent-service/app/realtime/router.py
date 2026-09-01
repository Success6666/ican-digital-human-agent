"""FastAPI mount point for the private realtime Agent socket."""

from __future__ import annotations

from fastapi import APIRouter, WebSocket

from .connection import RealtimeConnection
from .limits import DEFAULT_LIMITS


router = APIRouter()


@router.websocket("/internal/realtime")
async def realtime(websocket: WebSocket) -> None:
    """Accept only requests relayed by the authenticated gateway."""

    container = websocket.app.state.container
    await RealtimeConnection(
        websocket,
        container,
        limits=getattr(container, "realtime_limits", DEFAULT_LIMITS),
        ingress=getattr(container, "audio_ingress", None),
        output=getattr(container, "audio_output", None),
    ).run()


__all__ = ["realtime", "router"]
