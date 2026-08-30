from __future__ import annotations

import pytest

from app.settings import Settings


def test_runtime_limits_and_free_model_prices_are_configurable() -> None:
    settings = Settings(
        eval_input_price_per_1k=0,
        eval_output_price_per_1k=0,
        mcp_max_parallel_tools=8,
        rag_parse_concurrency=2,
        docling_max_concurrency=2,
        observability_max_pending_tasks=128,
        observability_pending_flush_timeout_seconds=1.5,
    )

    assert settings.eval_input_price_per_1k == 0
    assert settings.eval_output_price_per_1k == 0
    assert settings.mcp_max_parallel_tools == 8
    assert settings.rag_parse_concurrency == 2
    assert settings.docling_max_concurrency == 2
    assert settings.observability_max_pending_tasks == 128
    assert settings.observability_pending_flush_timeout_seconds == 1.5


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("eval_input_price_per_1k", -0.001),
        ("eval_output_price_per_1k", -0.001),
        ("eval_input_price_per_1k", float("nan")),
        ("eval_output_price_per_1k", float("inf")),
        ("mcp_max_parallel_tools", 0),
        ("rag_parse_concurrency", 0),
        ("docling_max_concurrency", 0),
        ("observability_max_pending_tasks", 0),
        ("observability_pending_flush_timeout_seconds", 0),
    ],
)
def test_runtime_limits_reject_invalid_values(field: str, value: float | int) -> None:
    with pytest.raises(ValueError):
        Settings(**{field: value})
