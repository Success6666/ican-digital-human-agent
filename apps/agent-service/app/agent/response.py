"""Build the stable output contract emitted by Agent Core."""

from __future__ import annotations

from typing import Any

from ..domain.models import AgentResponse


def build_agent_response(
    *,
    text: str,
    trace_id: str,
    session_id: str,
    run_id: str | None = None,
    performance: dict[str, Any] | None = None,
) -> AgentResponse:
    cue = performance if isinstance(performance, dict) else {}
    return AgentResponse(
        text=text,
        emotion=str(cue.get("expression") or "neutral"),
        gesture=str(cue["gesture"]) if cue.get("gesture") else None,
        performance=cue,
        traceId=trace_id,
        sessionId=session_id,
        runId=run_id,
        interruptible=bool(cue.get("interruptible", True)),
    )
