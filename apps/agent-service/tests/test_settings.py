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


def test_session_resource_defaults_are_bounded() -> None:
    settings = Settings()
    assert settings.session_max_sessions == 1024
    assert settings.session_cleanup_batch_size == 100
    assert settings.session_idle_timeout_seconds == 1800
    assert settings.session_heartbeat_interval_seconds == 15
    assert settings.realtime_handshake_timeout_seconds == 5.0
    assert settings.realtime_idle_timeout_seconds == 45.0
    assert settings.realtime_interrupt_timeout_seconds == 0.25


def test_session_resource_settings_load_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SESSION_MAX_SESSIONS", "32")
    monkeypatch.setenv("SESSION_CLEANUP_BATCH_SIZE", "7")
    monkeypatch.setenv("SESSION_IDLE_TIMEOUT_SECONDS", "90")
    monkeypatch.setenv("SESSION_HEARTBEAT_INTERVAL_SECONDS", "5")
    monkeypatch.setenv("REALTIME_HANDSHAKE_TIMEOUT_SECONDS", "7.5")
    monkeypatch.setenv("REALTIME_IDLE_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("REALTIME_INTERRUPT_TIMEOUT_SECONDS", "0.4")
    settings = Settings.from_env()
    assert settings.session_max_sessions == 32
    assert settings.session_cleanup_batch_size == 7
    assert settings.session_idle_timeout_seconds == 90
    assert settings.session_heartbeat_interval_seconds == 5
    assert settings.realtime_handshake_timeout_seconds == 7.5
    assert settings.realtime_idle_timeout_seconds == 30.0
    assert settings.realtime_interrupt_timeout_seconds == 0.4


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
        ("session_max_sessions", 0),
        ("session_max_sessions", 100001),
        ("session_cleanup_batch_size", 0),
        ("session_idle_timeout_seconds", 86401),
        ("session_heartbeat_interval_seconds", 0),
        ("realtime_handshake_timeout_seconds", 0),
        ("realtime_interrupt_timeout_seconds", 0),
    ],
)
def test_runtime_limits_reject_invalid_values(field: str, value: float | int) -> None:
    with pytest.raises(ValueError):
        Settings(**{field: value})


@pytest.mark.parametrize(
    ("heartbeat", "idle"),
    [(15, 15), (20, 10)],
)
def test_session_idle_timeout_must_exceed_heartbeat(heartbeat: int, idle: int) -> None:
    with pytest.raises(ValueError):
        Settings(
            session_heartbeat_interval_seconds=heartbeat,
            session_idle_timeout_seconds=idle,
        )


def test_realtime_idle_timeout_must_fit_between_heartbeat_and_session_lease() -> None:
    with pytest.raises(ValueError, match="realtime_idle_timeout_seconds must exceed"):
        Settings(realtime_idle_timeout_seconds=15, session_heartbeat_interval_seconds=15)
    with pytest.raises(ValueError, match="realtime_idle_timeout_seconds must not exceed"):
        Settings(session_idle_timeout_seconds=30)


def test_production_rejects_default_internal_tokens() -> None:
    with pytest.raises(ValueError, match="AGENT_INTERNAL_TOKEN"):
        Settings(environment="production", mcp_internal_token="mcp-production-token-" + "x" * 32)
    with pytest.raises(ValueError, match="MCP_INTERNAL_TOKEN"):
        Settings(environment="prod", internal_token="agent-production-token-" + "x" * 32)


@pytest.mark.parametrize(
    "token",
    [
        "replace-with-a-long-random-token",
        "replace-with-a-different-long-random-token",
        "x" * 31,
    ],
)
def test_production_rejects_public_or_short_tokens(token: str) -> None:
    with pytest.raises(ValueError, match="AGENT_INTERNAL_TOKEN"):
        Settings(
            environment="production",
            internal_token=token,
            mcp_internal_token="mcp-" + "x" * 40,
        )
    with pytest.raises(ValueError, match="MCP_INTERNAL_TOKEN"):
        Settings(
            environment="production",
            internal_token="agent-" + "x" * 40,
            mcp_internal_token=token,
        )


def test_production_accepts_explicit_internal_tokens() -> None:
    settings = Settings(
        environment="production",
        internal_token="agent-production-token-" + "x" * 32,
        mcp_internal_token="mcp-production-token-" + "y" * 32,
    )
    assert settings.environment == "production"
