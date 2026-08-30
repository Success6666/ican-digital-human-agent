from __future__ import annotations

from app.realtime.payloads import sanitize_event_data


def test_tool_event_exposes_summary_without_arguments_or_raw_result() -> None:
    data = sanitize_event_data(
        "tool",
        {
            "toolCalls": [
                {
                    "name": "weather",
                    "arguments": {"city": "北京"},
                    "result": {"temperature": 23, "secret": "hidden"},
                    "duration_ms": 12.345,
                }
            ]
        },
    )

    assert data == {
        "toolCalls": [
            {
                "name": "weather",
                "status": "ok",
                "durationMs": 12.35,
                "resultPreview": "已返回结构化结果",
            }
        ]
    }


def test_event_data_falls_back_when_custom_provider_payload_is_too_large() -> None:
    data = sanitize_event_data(
        "provider",
        {"message": "x" * 100_000, "raw": "hidden", **{f"field-{i}": "y" * 2_048 for i in range(64)}},
    )

    assert data["truncated"] is True
    assert len(data["message"]) <= 512
    assert "raw" not in data
