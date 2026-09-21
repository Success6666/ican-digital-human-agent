"""Internal-header authentication for the Agent realtime socket."""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass

from fastapi import WebSocket

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True, slots=True)
class RealtimeIdentity:
    user_id: str
    user_name: str


def read_identity(websocket: WebSocket, expected_token: str) -> RealtimeIdentity | None:
    """Validate the private gateway headers without accepting the socket."""

    supplied = websocket.headers.get("x-internal-token", "")
    if not supplied or not expected_token or not secrets.compare_digest(supplied, expected_token):
        return None
    user_id = _clean_header(websocket.headers.get("x-user-id"), identity=True)
    user_name = _clean_header(websocket.headers.get("x-user-name"))
    if not user_id or not user_name:
        return None
    return RealtimeIdentity(user_id=user_id, user_name=user_name)


async def reject(websocket: WebSocket, *, code: int = 4401) -> None:
    """Close before ``accept`` so an unauthenticated socket is never upgraded."""

    try:
        await websocket.close(code=code, reason="unauthorized")
    except Exception:
        # ASGI servers may already have discarded a failed handshake.
        return


def _clean_header(value: str | None, *, identity: bool = False) -> str:
    if not value:
        return ""
    clean = _CONTROL_CHARS.sub(" ", value).strip()
    if not clean:
        return ""
    if len(clean) <= 128:
        return clean
    digest = hashlib.sha256(clean.encode("utf-8")).hexdigest()[:31]
    prefix = 96 if identity else 80
    return f"{clean[:prefix]}:{digest}"


__all__ = ["RealtimeIdentity", "read_identity", "reject"]
