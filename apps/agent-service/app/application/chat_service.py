"""Chat use cases wrapping validation, ownership and graph execution."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import time
from typing import Any

from ..agent.security import assess_prompt_injection
from ..evaluation.metrics import looks_like_prompt_injection, looks_like_safe_refusal
from ..evaluation.models import EvaluationRunRequest
from ..evaluation.service import EvaluationService
from ..domain.models import ChatResult
from ..graph.runtime import AgentGraphRuntime
from .errors import InvalidMessageError
from .session_service import SessionApplicationService


class ChatApplicationService:
    def __init__(
        self,
        *,
        graph: AgentGraphRuntime,
        sessions: SessionApplicationService,
        max_message_length: int = 4000,
        evaluation: EvaluationService | None = None,
    ) -> None:
        self.graph = graph
        self.sessions = sessions
        self.max_message_length = max_message_length
        self.evaluation = evaluation

    async def send(self, *, user_id: str, user_name: str, session_id: str, message: str) -> ChatResult:
        clean = self._validate(message)
        await self.sessions.get_for_user(user_id=user_id, session_id=session_id)
        run_id = await self.sessions.begin_run(user_id=user_id, session_id=session_id)
        started = time.perf_counter()
        try:
            result = await self.graph.invoke(
                user_id=user_id,
                user_name=user_name,
                session_id=session_id,
                message=clean,
                run_id=run_id,
            )
        except Exception as exc:
            self._record(
                user_id=user_id,
                message=clean,
                output="",
                status="interrupted" if exc.__class__.__name__ == "RunInterrupted" else "error",
                trace_id=None,
                tools=[],
                agent_latency_ms=(time.perf_counter() - started) * 1000,
                digital_human_latency_ms=None,
            )
            raise
        self._record_result(user_id=user_id, message=clean, result=result, elapsed_ms=(time.perf_counter() - started) * 1000)
        return result

    async def stream(
        self, *, user_id: str, user_name: str, session_id: str, message: str
    ) -> AsyncIterator[dict[str, Any]]:
        clean = self._validate(message)
        await self.sessions.get_for_user(user_id=user_id, session_id=session_id)
        run_id = await self.sessions.begin_run(user_id=user_id, session_id=session_id)
        if not run_id:
            raise InvalidMessageError("session is not available")
        return self._stream_events(
            user_id=user_id,
            user_name=user_name,
            session_id=session_id,
            message=clean,
            run_id=run_id,
        )

    async def _stream_events(
        self, *, user_id: str, user_name: str, session_id: str, message: str, run_id: str
    ) -> AsyncIterator[dict[str, Any]]:
        started = time.perf_counter()
        trace_id: str | None = None
        status = "success"
        interrupted = False
        done_data: dict[str, Any] = {}
        deltas: list[str] = []
        tools: list[str] = []
        recorded = False
        try:
            async for event in self.graph.stream(
                user_id=user_id,
                user_name=user_name,
                session_id=session_id,
                message=message,
                run_id=run_id,
            ):
                if isinstance(event, dict):
                    data = event.get("data")
                    payload = data if isinstance(data, dict) else {}
                    trace_id = str(payload.get("traceId") or trace_id or "") or trace_id
                    event_name = str(event.get("event") or "")
                    if event_name == "delta" and payload.get("text"):
                        deltas.append(str(payload["text"]))
                    elif event_name == "tool":
                        for item in payload.get("toolCalls", []):
                            if isinstance(item, dict) and item.get("name"):
                                tools.append(str(item["name"]))
                            if isinstance(item, dict) and item.get("error"):
                                status = "error"
                    elif event_name == "provider" and payload.get("status") == "error":
                        status = "error"
                    elif event_name == "error":
                        status = "error"
                    elif event_name == "interrupted":
                        status = "interrupted"
                        interrupted = True
                    elif event_name == "done":
                        done_data = payload
                        interrupted = bool(payload.get("interrupted"))
                        if interrupted:
                            status = "interrupted"
                        elif payload.get("provider") == "unknown":
                            status = "error"
                        recorded = True
                yield event
        except asyncio.CancelledError:
            if not recorded:
                self._record_stream(
                    user_id=user_id,
                    message=message,
                    trace_id=trace_id,
                    output="".join(deltas),
                    status="interrupted",
                    tools=tools,
                    done_data=done_data,
                    elapsed_ms=(time.perf_counter() - started) * 1000,
                )
            raise
        except Exception:
            if not recorded:
                self._record_stream(
                    user_id=user_id,
                    message=message,
                    trace_id=trace_id,
                    output="".join(deltas),
                    status="error",
                    tools=tools,
                    done_data=done_data,
                    elapsed_ms=(time.perf_counter() - started) * 1000,
                )
            raise
        else:
            self._record_stream(
                user_id=user_id,
                message=message,
                trace_id=trace_id,
                output=str(done_data.get("reply") or "".join(deltas)),
                status=status,
                tools=tools,
                done_data=done_data,
                elapsed_ms=(time.perf_counter() - started) * 1000,
            )

    async def validate_and_authorize(self, *, user_id: str, session_id: str, message: str) -> str:
        """Validate input and ownership before an HTTP streaming response starts."""
        clean = self._validate(message)
        await self.sessions.get_for_user(user_id=user_id, session_id=session_id)
        return clean

    def _validate(self, message: str) -> str:
        clean = message.strip()
        if not clean:
            raise InvalidMessageError("message must not be empty")
        if len(clean) > self.max_message_length:
            raise InvalidMessageError(f"message exceeds {self.max_message_length} characters")
        return clean

    def _record_result(self, *, user_id: str, message: str, result: ChatResult, elapsed_ms: float) -> None:
        status = _result_status(result)
        self._record(
            user_id=user_id,
            message=message,
            output=result.reply,
            status=status,
            trace_id=result.trace_id,
            tools=[item.name for item in result.tool_calls],
            agent_latency_ms=result.agent_latency_ms or elapsed_ms,
            digital_human_latency_ms=result.digital_human_latency_ms,
        )

    def _record_stream(
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
        if status == "success":
            if done_data.get("provider") == "unknown":
                status = "error"
            elif any(isinstance(item, dict) and item.get("error") for item in done_data.get("toolCalls", [])):
                status = "error"
        self._record(
            user_id=user_id,
            message=message,
            output=output,
            status=status if status in {"success", "error", "interrupted"} else "success",
            trace_id=trace_id,
            tools=tools,
            agent_latency_ms=_number(done_data.get("agentLatencyMs")) or elapsed_ms,
            digital_human_latency_ms=_number(done_data.get("digitalHumanLatencyMs")),
        )

    def _record(
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
    ) -> None:
        if self.evaluation is None:
            return
        # Keep the evaluation signal aligned with the graph security gate;
        # the metric helper also covers offline samples that do not enter the
        # runtime graph.
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
                    agent_latency_ms=max(0.0, agent_latency_ms) if agent_latency_ms is not None else None,
                    digital_human_latency_ms=max(0.0, digital_human_latency_ms)
                    if digital_human_latency_ms is not None
                    else None,
                ),
                owner_id=user_id,
            )
        except Exception:
            # Evaluation must never make the user-facing chat fail.
            return


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and value >= 0 else None


def _result_status(result: ChatResult) -> str:
    if result.interrupted:
        return "interrupted"
    if result.provider == "unknown" or any(call.error for call in result.tool_calls):
        return "error"
    return "success"
