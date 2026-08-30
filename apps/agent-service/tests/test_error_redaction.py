from __future__ import annotations

from app.graph.builder_support import safe_error as builder_safe_error
from app.graph.runtime_support import safe_error as runtime_safe_error
from app.mcp.client import _safe_error as mcp_safe_error


def test_runtime_errors_redact_credentials_before_transport() -> None:
    error = RuntimeError(
        "authorization: Bearer super-secret-token password=hunter2 token=opaque-value"
    )

    for safe_error in (runtime_safe_error, builder_safe_error, mcp_safe_error):
        message = safe_error(error)
        assert "super-secret-token" not in message
        assert "hunter2" not in message
        assert "opaque-value" not in message
        assert "[REDACTED]" in message
