from __future__ import annotations

import json
from typing import Any

import pytest

from app.domain.models import ToolCallRecord
from app.mcp.client import CompositeToolClient, LocalToolClient
from app.mcp.limits import MIN_MAX_RESULT_BYTES, ToolResultLimiter
from app.settings import Settings


def _json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8"))


def test_limiter_keeps_text_result_under_byte_limit() -> None:
    limiter = ToolResultLimiter(max_bytes=64, max_items=4, max_depth=3)

    bounded, metadata = limiter.apply("你好" * 500)

    assert _json_size(bounded) <= 64
    assert metadata["result_truncated"] is True
    assert metadata["result_original_bytes_capped"] is True
    assert "bytes" in metadata["result_truncation_reasons"]


def test_limiter_bounds_items_and_nested_depth() -> None:
    limiter = ToolResultLimiter(max_bytes=4096, max_items=2, max_depth=2)
    value = {
        "items": [{"id": index, "nested": {"secret": "value"}} for index in range(8)],
        "deep": {"level": {"another": {"value": "hidden"}}},
    }

    bounded, metadata = limiter.apply(value)

    assert _json_size(bounded) <= 4096
    assert len(bounded["items"]) == 2
    assert bounded["items"][0]["nested"] == "[nested value omitted]"
    assert bounded["deep"]["level"]["another"] == "[nested value omitted]"
    assert set(metadata["result_truncation_reasons"]) >= {"items", "depth"}


@pytest.mark.asyncio
async def test_local_client_applies_result_limit_at_mcp_boundary() -> None:
    limiter = ToolResultLimiter(max_bytes=80, max_items=3, max_depth=3)
    client = LocalToolClient(result_limiter=limiter)

    async def huge_result(arguments: dict[str, Any]) -> dict[str, Any]:
        return {"payload": "x" * 1000}

    client._tools["huge"] = huge_result
    record = await client.call("huge")

    assert record.error is None
    assert record.metadata["result_truncated"] is True
    assert _json_size(record.result) <= 80


@pytest.mark.asyncio
async def test_composite_fallback_preserves_limit_metadata() -> None:
    limiter = ToolResultLimiter(max_bytes=96, max_items=3, max_depth=3)

    class RemoteDown:
        result_limiter = limiter

        async def call(self, name: str, arguments: dict[str, Any] | None = None) -> ToolCallRecord:
            return ToolCallRecord(name=name, arguments=arguments or {}, error="remote unavailable")

    local = LocalToolClient(result_limiter=limiter)

    async def huge_result(arguments: dict[str, Any]) -> dict[str, Any]:
        return {"payload": "x" * 1000}

    local._tools["huge"] = huge_result
    client = CompositeToolClient(RemoteDown(), local, allow_fallback=True, remote_budget_seconds=None)

    record = await client.call("huge")

    assert record.metadata["fallback"] is True
    assert record.metadata["result_truncated"] is True
    assert _json_size(record.result) <= 96


def test_result_limit_settings_are_environment_backed() -> None:
    settings = Settings(
        MCP_MAX_RESULT_BYTES=2048,
        MCP_MAX_RESULT_ITEMS=12,
        MCP_MAX_RESULT_DEPTH=4,
    )

    assert settings.mcp_max_result_bytes == 2048
    assert settings.mcp_max_result_items == 12
    assert settings.mcp_max_result_depth == 4


def test_result_limit_rejects_an_impossible_wire_budget() -> None:
    with pytest.raises(ValueError, match=str(MIN_MAX_RESULT_BYTES)):
        ToolResultLimiter(max_bytes=MIN_MAX_RESULT_BYTES - 1)
