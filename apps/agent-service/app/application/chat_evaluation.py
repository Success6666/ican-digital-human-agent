"""Evaluation recording for synchronous and streaming chat runs."""

from __future__ import annotations

import math
from typing import Any

from ..agent.security import assess_prompt_injection
from ..domain.models import ChatResult
from ..evaluation.metrics import looks_like_prompt_injection, looks_like_safe_refusal
from ..evaluation.models import EvaluationRunRequest
from ..evaluation.service import EvaluationService


class ChatEvaluationRecorder:
    """Translate chat outcomes into bounded, owner-scoped evaluation runs."""

    def __init__(self, evaluation: EvaluationService | None) -> None:
        self.evaluation = evaluation

    def record_result(self, *, user_id: str, message: str, result: ChatResult, elapsed_ms: float) -> None:
        self.record(
            user_id=user_id,
            message=message,
            output=result.reply,
            status=result_status(result),
            trace_id=result.trace_id,
            tools=[item.name for item in result.tool_calls],
            agent_latency_ms=result.agent_latency_ms or elapsed_ms,
            digital_human_latency_ms=result.digital_human_latency_ms,
            first_event_latency_ms=result.first_event_latency_ms,
            first_visible_latency_ms=result.first_visible_latency_ms,
            cancellation_latency_ms=result.cancellation_latency_ms,
        )

    def record_stream(
        self,
        *,
        user_id: str,
        message: str,
        trace_id: str | None,
        output: str,
        status: str,
        tools: list[str],
        done_data: dict[str, Any],
        elapsed_ms: float,
    ) -> None:
        if status == "success" and (
            done_data.get("provider") == "unknown"
            or any(
                isinstance(item, dict) and item.get("error")
                for item in done_data.get("toolCalls", [])
            )
        ):
            status = "error"
        first_event_latency = number(done_data.get("firstEventLatencyMs"))
        first_visible_latency = number(done_data.get("firstVisibleLatencyMs"))
        cancellation_latency = number(done_data.get("cancellationLatencyMs"))
        self.record(
            user_id=user_id,
            message=message,
            output=output,
            status=status if status in {"success", "error", "interrupted"} else "success",
            trace_id=trace_id,
            tools=tools,
            agent_latency_ms=number(done_data.get("agentLatencyMs")) or elapsed_ms,
            digital_human_latency_ms=number(done_data.get("digitalHumanLatencyMs")),
            first_event_latency_ms=first_event_latency,
            first_visible_latency_ms=first_visible_latency,
            cancellation_latency_ms=(
                cancellation_latency
                if cancellation_latency is not None
                else elapsed_ms
                if status == "interrupted"
                else None
            ),
        )

    def record(
        self,
        *,
        user_id: str,
        message: str,
        output: str,
        status: str,
        trace_id: str | None,
        tools: list[str],
        agent_latency_ms: float | None,
        digital_human_latency_ms: float | None,
        first_event_latency_ms: float | None = None,
        first_visible_latency_ms: float | None = None,
        cancellation_latency_ms: float | None = None,
    ) -> None:
        if self.evaluation is None:
            return
        injection = looks_like_prompt_injection(message) or assess_prompt_injection(message).attempted
        recorded_status = status if status in {"success", "error", "interrupted", "blocked"} else "error"
        if injection and looks_like_safe_refusal(output):
            recorded_status = "blocked"
        try:
            self.evaluation.record(
                EvaluationRunRequest(
                    input_text=message,
                    output_text=output,
                    status=recorded_status,
                    trace_id=trace_id,
                    actual_tools=sorted(set(tools)),
                    injection_attempt=injection,
                    injection_blocked=looks_like_safe_refusal(output) if injection else None,
                    agent_latency_ms=_non_negative(agent_latency_ms),
                    digital_human_latency_ms=_non_negative(digital_human_latency_ms),
                    first_event_latency_ms=_non_negative(first_event_latency_ms),
                    first_visible_latency_ms=_non_negative(first_visible_latency_ms),
                    cancellation_latency_ms=_non_negative(cancellation_latency_ms),
                ),
                owner_id=user_id,
            )
        except Exception:
            # Evaluation must never make the user-facing chat fail.
            return


def number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) and parsed >= 0 else None


def result_status(result: ChatResult) -> str:
    if result.interrupted:
        return "interrupted"
    if result.provider == "unknown" or any(call.error for call in result.tool_calls):
        return "error"
    return "success"


def _non_negative(value: float | None) -> float | None:
    return number(value)


__all__ = ["ChatEvaluationRecorder", "number", "result_status"]
