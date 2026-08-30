"""Small helpers for stable, human-readable agent stream payloads."""

from __future__ import annotations

from typing import Any

from .models import FillerPlan
from ..domain.models import ChatResult, ToolCallRecord


def filler_payload(trace_id: str, filler: FillerPlan, *, run_id: str | None = None) -> dict[str, Any]:
    return {
        "traceId": trace_id,
        "runId": run_id,
        "text": filler.text,
        "phase": filler.phase,
        "expectedDelayMs": filler.expected_delay_ms,
        "performance": filler.cue.model_dump(mode="json", by_alias=True),
    }


def provider_performance(payload: dict[str, Any]) -> dict[str, Any] | None:
    result = payload.get("provider_result")
    metadata = result.get("metadata", {}) if isinstance(result, dict) else getattr(result, "metadata", {})
    value = metadata.get("performance") if isinstance(metadata, dict) else None
    return value if isinstance(value, dict) else None


def chunks(text: str, size: int = 12) -> list[str]:
    return [text[index : index + size] for index in range(0, len(text), size)] or [""]


def dump_tools(calls: list[ToolCallRecord]) -> list[dict[str, Any]]:
    return [call.model_dump(mode="json") if isinstance(call, ToolCallRecord) else call for call in calls]


def result_payload(result: ChatResult) -> dict[str, Any]:
    return {
        "reply": result.reply,
        "traceId": result.trace_id,
        "sessionId": result.session_id,
        "runId": result.run_id,
        "provider": result.provider,
        "toolCalls": dump_tools(result.tool_calls),
        "agentLatencyMs": result.agent_latency_ms,
        "digitalHumanLatencyMs": result.digital_human_latency_ms,
        "firstEventLatencyMs": result.first_event_latency_ms,
        "firstVisibleLatencyMs": result.first_visible_latency_ms,
        "cancellationLatencyMs": result.cancellation_latency_ms,
        "interrupted": result.interrupted,
        "agentResponse": result.agent_response.model_dump(mode="json", by_alias=True)
        if result.agent_response
        else None,
    }
