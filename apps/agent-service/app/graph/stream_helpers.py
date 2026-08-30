"""Transport-facing helpers for the LangGraph stream."""

from __future__ import annotations

from collections.abc import Iterator
import time
from typing import Any

from ..agent.models import FillerPhase
from ..agent.security import reason_label
from ..agent.streaming import chunks, dump_tools, provider_performance


def node_event(
    node_name: str,
    payload: dict[str, Any],
    *,
    trace_id: str,
    run_id: str | None,
) -> dict[str, Any] | None:
    """Translate one graph update into a browser-safe event."""
    if node_name == "retrieve":
        if payload.get("security_blocked"):
            return None
        return {
            "event": "rag",
            "data": {
                "traceId": trace_id,
                "runId": run_id,
                "hitCount": len(payload.get("rag_hits", [])),
                "degraded": bool(payload.get("rag_error")),
            },
        }
    if node_name == "security":
        blocked = bool(payload.get("security_blocked"))
        return {
            "event": "security",
            "data": {
                "traceId": trace_id,
                "runId": run_id,
                "blocked": blocked,
                "reason": reason_label(payload.get("security_reason")) if blocked else None,
            },
        }
    if node_name == "tool":
        if payload.get("security_blocked"):
            return None
        return {
            "event": "tool",
            "data": {
                "traceId": trace_id,
                "runId": run_id,
                "toolCalls": dump_tools(payload.get("tool_calls", [])),
            },
        }
    if node_name == "provider":
        provider_result = payload.get("provider_result")
        provider_result_status = (
            provider_result.get("status")
            if isinstance(provider_result, dict)
            else getattr(provider_result, "status", None)
        )
        normalized_result_status = str(provider_result_status or "ok").casefold()
        provider_status = (
            "interrupted"
            if payload.get("interrupted") or normalized_result_status in {"interrupted", "cancelled", "canceled"}
            else "error"
            if payload.get("provider_error") or normalized_result_status in {"error", "failed"}
            else "ok"
        )
        return {
            "event": "provider",
            "data": {
                "traceId": trace_id,
                "runId": run_id,
                "status": provider_status,
                "message": payload.get("provider_error"),
                "performance": provider_performance(payload),
            },
        }
    return None


def response_events(
    payload: dict[str, Any],
    *,
    trace_id: str,
    run_id: str | None,
    runtime: Any,
) -> Iterator[dict[str, Any]]:
    """Build response deltas lazily; the caller performs stop checks."""
    reply = str(payload.get("reply", ""))
    for index, chunk in enumerate(chunks(reply)):
        data: dict[str, Any] = {
            "traceId": trace_id,
            "runId": run_id,
            "text": chunk,
        }
        if index == 0:
            data["performance"] = runtime._performance.for_phase(FillerPhase.SPEAKING).model_dump(
                mode="json", by_alias=True
            )
        yield {"event": "delta", "data": data}


def elapsed_ms(started_at: float) -> float:
    return round(max(0.0, (time.perf_counter() - started_at) * 1000), 2)


def latency_payload(
    first_event_latency_ms: float | None,
    first_visible_latency_ms: float | None,
    cancellation_latency: float | None = None,
) -> dict[str, float | None]:
    return {
        "firstEventLatencyMs": first_event_latency_ms,
        "firstVisibleLatencyMs": first_visible_latency_ms,
        "cancellationLatencyMs": cancellation_latency,
    }


async def invalidate_run(runtime: Any, *, session_id: str, run_id: str) -> None:
    """Invalidate a run when its stream closes before a terminal event."""
    marker = getattr(runtime._sessions, "mark_interrupted", None)
    if not callable(marker):
        return
    try:
        await marker(session_id, run_id=run_id)
    except Exception:
        # Disconnect cleanup is best effort and must not mask the original
        # stream cancellation or provider error.
        return


__all__ = ["elapsed_ms", "invalidate_run", "latency_payload", "node_event", "response_events"]
