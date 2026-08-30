"""Filter provider session parameters before they cross the browser boundary."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse


_TEXT_LIMITS = {
    "mode": 64,
    "protocol": 32,
    "codec": 32,
    "expiresAt": 128,
    "endpoint": 4096,
    "wsUrl": 4096,
    "websocketUrl": 4096,
    "realtimeUrl": 4096,
}
_NUMBER_LIMITS = {
    "sampleRate": (8_000, 96_000),
    "channels": (1, 2),
    "frameMs": (5, 100),
    "maxFrameBytes": (320, 1_048_576),
    "heartbeatMs": (1_000, 300_000),
}
_NESTED_KEYS = frozenset(_TEXT_LIMITS) | frozenset(_NUMBER_LIMITS)


def browser_safe_client_params(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return only short-lived, non-secret parameters needed by a browser adapter.

    Provider SDK credentials, tickets and arbitrary metadata are intentionally
    excluded here. Frontend normalization is a convenience layer, not a
    security boundary.
    """
    if not isinstance(value, Mapping):
        return {}
    result = _filter(value)
    nested = value.get("realtime")
    if isinstance(nested, Mapping):
        safe_nested = _filter(nested)
        if safe_nested:
            result["realtime"] = safe_nested
    return result


def _filter(value: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, limit in _TEXT_LIMITS.items():
        candidate = value.get(key)
        if not isinstance(candidate, str):
            continue
        text = candidate.strip()
        if not text or len(text) > limit:
            continue
        if key in {"endpoint", "wsUrl", "websocketUrl", "realtimeUrl"} and not _safe_url(text):
            continue
        result[key] = text
    for key, (minimum, maximum) in _NUMBER_LIMITS.items():
        candidate = value.get(key)
        if isinstance(candidate, bool) or not isinstance(candidate, (int, float)):
            continue
        if isinstance(candidate, float) and not candidate.is_integer():
            continue
        number = int(candidate)
        if minimum <= number <= maximum:
            result[key] = number
    return result


def _safe_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"https", "wss"} and bool(parsed.netloc) and not parsed.username


__all__ = ["browser_safe_client_params"]
