"""Browser-safe shaping for graph events crossing the realtime boundary."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from ..observability.redaction import redact, redact_text

MAX_EVENT_BYTES = 64 * 1024
_SECRET_OR_INTERNAL_KEYS = frozenset(
    {"arguments", "args", "raw", "headers", "authorization", "clientParams", "client_params"}
)


def sanitize_event_data(event_type: str, value: Any) -> dict[str, Any]:
    """Keep event fields useful to a person while bounding untrusted values."""
    data = dict(value) if isinstance(value, Mapping) else {"value": value}
    if event_type == "tool":
        shaped = {"toolCalls": summarize_tool_calls(data.get("toolCalls", data.get("tool_calls", [])))}
    else:
        shaped = _bounded_mapping(data)
    return fit_event_data(shaped)


def fit_event_data(value: Mapping[str, Any], *, max_bytes: int = MAX_EVENT_BYTES) -> dict[str, Any]:
    """Fit a shaped event to a deterministic JSON byte budget."""
    safe = dict(value)
    if _json_size(safe) <= max_bytes:
        return safe
    # Text and diagnostic fields are the most useful fallback. Do not return
    # arbitrary nested provider payloads when a custom adapter exceeds budget.
    fallback: dict[str, Any] = {"truncated": True, "message": "事件内容过大，已隐藏详细数据"}
    for key in ("text", "message", "status", "phase", "code"):
        candidate = safe.get(key)
        if isinstance(candidate, str):
            fallback[key] = redact_text(candidate, max_length=480)
    return fallback


def summarize_tool_calls(value: Any) -> list[dict[str, Any]]:
    """Expose tool status without sending arguments or raw MCP results."""
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    result: list[dict[str, Any]] = []
    for item in list(value)[:32]:
        if not isinstance(item, Mapping):
            continue
        name = _text(item.get("name"), 128) or "未命名工具"
        error = _text(item.get("error"), 300)
        summary: dict[str, Any] = {
            "name": name,
            "status": "error" if error else "ok",
        }
        if error:
            summary["error"] = error
        duration = item.get("durationMs", item.get("duration_ms"))
        if isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration >= 0:
            summary["durationMs"] = round(float(duration), 2)
        preview = _result_preview(item.get("result"))
        if preview:
            summary["resultPreview"] = preview
        result.append(summary)
    return result


def _bounded_mapping(value: Mapping[str, Any], *, depth: int = 0) -> dict[str, Any]:
    if depth > 5:
        return {"truncated": True}
    safe: dict[str, Any] = {}
    for index, (key, item) in enumerate(value.items()):
        if index >= 64:
            safe["truncated"] = True
            break
        name = str(key)
        if name in _SECRET_OR_INTERNAL_KEYS:
            continue
        safe[name] = _bounded_value(item, depth=depth + 1)
    return redact(safe)


def _bounded_value(value: Any, *, depth: int) -> Any:
    if depth > 5:
        return "[TRUNCATED]"
    if isinstance(value, Mapping):
        return _bounded_mapping(value, depth=depth)
    if isinstance(value, (list, tuple)):
        return [_bounded_value(item, depth=depth + 1) for item in list(value)[:64]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return redact_text(str(value), max_length=512) or "[REDACTED]"


def _result_preview(value: Any) -> str | None:
    if value is None:
        return None
    safe = redact(value)
    if isinstance(safe, (dict, list)):
        return "已返回结构化结果"
    return redact_text(str(safe), max_length=512)


def _text(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    clean = value.strip()
    return clean[:limit] if clean else None


def _json_size(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError):
        return MAX_EVENT_BYTES + 1


__all__ = ["MAX_EVENT_BYTES", "fit_event_data", "sanitize_event_data", "summarize_tool_calls"]
