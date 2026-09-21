"""Bound MCP tool results before they enter graph state or API payloads.

The MCP SDK has to materialize a tool response before this boundary can see
it.  This module therefore focuses on the next important containment point:
large or deeply nested results must not fan out into LangGraph state, traces,
session memory and browser responses.  The policy is immutable and can be
shared by all clients in a service container.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..domain.models import ToolCallRecord

DEFAULT_MAX_RESULT_BYTES = 64 * 1024
DEFAULT_MAX_RESULT_ITEMS = 256
DEFAULT_MAX_RESULT_DEPTH = 8
MIN_MAX_RESULT_BYTES = 16

_TRUNCATION_MARKER = "...[MCP result truncated]"
_NESTED_VALUE_MARKER = "[nested value omitted]"


@dataclass(frozen=True, slots=True)
class ToolResultLimiter:
    """Deterministically reduce an MCP result to a bounded JSON payload."""

    max_bytes: int = DEFAULT_MAX_RESULT_BYTES
    max_items: int = DEFAULT_MAX_RESULT_ITEMS
    max_depth: int = DEFAULT_MAX_RESULT_DEPTH

    def __post_init__(self) -> None:
        if self.max_bytes < MIN_MAX_RESULT_BYTES:
            raise ValueError(f"max_bytes must be at least {MIN_MAX_RESULT_BYTES}")
        if self.max_items <= 0:
            raise ValueError("max_items must be positive")
        if self.max_depth <= 0:
            raise ValueError("max_depth must be positive")

    def apply(self, value: Any) -> tuple[Any, dict[str, Any]]:
        """Return a bounded value and metadata when anything was clipped."""

        original_bytes = _serialized_size(value, self.max_bytes)
        reasons: set[str] = set()
        bounded = self._clip(value, depth=0, budget=self.max_bytes, reasons=reasons)
        encoded = _json_bytes(bounded)
        if len(encoded) > self.max_bytes:
            bounded = _fit_json_value(bounded, self.max_bytes)
            reasons.add("bytes")
            encoded = _json_bytes(bounded)

        if not reasons and original_bytes <= self.max_bytes:
            return value, {}

        # `original_bytes` is capped at max_bytes + 1 to avoid allocating a
        # second copy of an untrusted multi-megabyte response just for metrics.
        return bounded, {
            "result_truncated": True,
            "result_original_bytes": original_bytes,
            "result_original_bytes_capped": original_bytes > self.max_bytes,
            "result_returned_bytes": len(encoded),
            "result_limit_bytes": self.max_bytes,
            "result_limit_items": self.max_items,
            "result_limit_depth": self.max_depth,
            "result_truncation_reasons": sorted(reasons or {"bytes"}),
        }

    def limit_record(self, record: ToolCallRecord) -> ToolCallRecord:
        """Apply the policy to a record while preserving existing metadata."""

        bounded, metadata = self.apply(record.result)
        if not metadata:
            return record
        return record.model_copy(
            update={
                "result": bounded,
                "metadata": {**record.metadata, **metadata},
            }
        )

    def _clip(self, value: Any, *, depth: int, budget: int, reasons: set[str]) -> Any:
        if isinstance(value, str):
            bounded = _truncate_text(value, budget)
            if bounded != value:
                reasons.add("bytes")
            return bounded
        if isinstance(value, bytes):
            bounded = _truncate_text(value.decode("utf-8", errors="replace"), budget)
            if len(value) > budget:
                reasons.add("bytes")
            return bounded
        if isinstance(value, (dict, list, tuple, set)) and depth > self.max_depth:
            reasons.add("depth")
            return _NESTED_VALUE_MARKER

        if isinstance(value, dict):
            items = list(value.items())
            if len(items) > self.max_items:
                reasons.add("items")
            selected = items[: self.max_items]
            output: dict[str, Any] = {}
            count = max(1, len(selected))
            child_budget = max(8, budget // count)
            for key, item in selected:
                output[_clip_key(key, budget)] = self._clip(
                    item,
                    depth=depth + 1,
                    budget=child_budget,
                    reasons=reasons,
                )
            return output

        if isinstance(value, (list, tuple, set)):
            values = list(value)
            if isinstance(value, set):
                values.sort(key=repr)
            if len(values) > self.max_items:
                reasons.add("items")
            selected = values[: self.max_items]
            count = max(1, len(selected))
            child_budget = max(8, budget // count)
            return [
                self._clip(item, depth=depth + 1, budget=child_budget, reasons=reasons)
                for item in selected
            ]

        if value is None or isinstance(value, (bool, int, float)):
            return value

        # Pydantic models and SDK result objects are converted without adding a
        # dependency on either library to the MCP boundary.
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            try:
                return self._clip(model_dump(mode="json"), depth=depth, budget=budget, reasons=reasons)
            except Exception:  # pragma: no cover - defensive SDK boundary
                pass
        return _truncate_text(str(value), budget)


def _truncate_text(value: str, max_bytes: int) -> str:
    raw = value.encode("utf-8", errors="replace")
    if len(raw) <= max_bytes:
        return value
    marker = _TRUNCATION_MARKER.encode("utf-8")
    if max_bytes <= len(marker):
        return raw[:max_bytes].decode("utf-8", errors="ignore")
    prefix = raw[: max_bytes - len(marker)].decode("utf-8", errors="ignore")
    return prefix + _TRUNCATION_MARKER


def _fit_json_value(value: Any, max_bytes: int) -> Any:
    """Fit a value by JSON wire size, preserving a useful text preview."""

    if len(_json_bytes(value)) <= max_bytes:
        return value
    text = value if isinstance(value, str) else _json_bytes(value).decode("utf-8", errors="replace")
    marker = _TRUNCATION_MARKER
    if len(_json_bytes(marker)) > max_bytes:
        return _fit_text_without_marker(text, max_bytes)

    # Character binary search keeps the operation bounded even for very large
    # tool responses and accounts for JSON quotes/escaping around the string.
    low, high = 0, len(text)
    best = marker
    while low <= high:
        middle = (low + high) // 2
        candidate = text[:middle] + marker
        if len(_json_bytes(candidate)) <= max_bytes:
            best = candidate
            low = middle + 1
        else:
            high = middle - 1
    return best


def _fit_text_without_marker(value: str, max_bytes: int) -> str:
    low, high = 0, len(value)
    best = ""
    while low <= high:
        middle = (low + high) // 2
        candidate = value[:middle]
        if len(_json_bytes(candidate)) <= max_bytes:
            best = candidate
            low = middle + 1
        else:
            high = middle - 1
    return best


def _clip_key(key: Any, budget: int) -> str:
    # JSON object keys are strings.  Capping them separately prevents a single
    # attacker-controlled key from consuming the entire result budget.
    return _truncate_text(str(key), max(8, min(256, budget // 2 or 8)))


def _json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            default=_json_default,
        ).encode("utf-8", errors="replace")
    except Exception:  # pragma: no cover - defensive serialization boundary
        return str(value).encode("utf-8", errors="replace")


def _json_default(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return model_dump(mode="json")
        except Exception:  # pragma: no cover - defensive SDK boundary
            pass
    return str(value)


def _serialized_size(value: Any, cap: int) -> int:
    """Estimate JSON bytes, returning cap + 1 as soon as the cap is crossed."""

    if isinstance(value, str):
        return min(cap + 1, len(_json_bytes(value)))
    if isinstance(value, bytes):
        return min(cap + 1, len(_json_bytes(value.decode("utf-8", errors="replace"))))
    if value is None:
        return 4
    if isinstance(value, bool):
        return 4 if value else 5
    if isinstance(value, (int, float)):
        return min(cap + 1, len(str(value).encode("utf-8")))
    if isinstance(value, dict):
        total = 2
        for key, item in value.items():
            total += len(_json_bytes(str(key))) + 1
            if total > cap:
                return cap + 1
            child_cap = cap - total
            total += _serialized_size(item, child_cap)
            if total > cap:
                return cap + 1
            total += 1
        return min(cap + 1, total)
    if isinstance(value, (list, tuple, set)):
        total = 2
        values = sorted(value, key=repr) if isinstance(value, set) else value
        for item in values:
            total += _serialized_size(item, max(0, cap - total))
            if total > cap:
                return cap + 1
            total += 1
        return min(cap + 1, total)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _serialized_size(model_dump(mode="json"), cap)
        except Exception:  # pragma: no cover - defensive SDK boundary
            pass
    return min(cap + 1, len(_json_bytes(value)))
