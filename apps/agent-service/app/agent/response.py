"""Build the stable output contract emitted by Agent Core."""

from __future__ import annotations

from typing import Any

from .models import PerformanceCue
from ..domain.models import AgentResponse


def build_agent_response(
    *,
    text: str,
    trace_id: str,
    session_id: str,
    run_id: str | None = None,
    performance: dict[str, Any] | None = None,
    presentation: PerformanceCue | dict[str, Any] | None = None,
) -> AgentResponse:
    raw_cue = presentation if presentation is not None else performance
    try:
        cue_model = raw_cue if isinstance(raw_cue, PerformanceCue) else PerformanceCue.model_validate(raw_cue or {})
    except Exception:
        cue_model = PerformanceCue(expression="speaking", lipSync=True)
    cue = cue_model.model_dump(mode="json", by_alias=True)
    return AgentResponse(
        text=text,
        emotion=str(cue.get("expression") or "neutral"),
        gesture=str(cue["gesture"]) if cue.get("gesture") else None,
        presentation=cue,
        performance=cue,
        traceId=trace_id,
        sessionId=session_id,
        runId=run_id,
        interruptible=bool(cue.get("interruptible", True)),
    )
