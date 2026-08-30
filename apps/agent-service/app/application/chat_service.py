"""Chat use cases wrapping validation, ownership and graph execution."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import time
from typing import Any

from ..evaluation.service import EvaluationService
from ..domain.models import ChatResult
from ..graph.runtime import AgentGraphRuntime
from .chat_evaluation import ChatEvaluationRecorder
from .chat_evaluation import number as _number_value
from .chat_evaluation import result_status as _result_status_value
from .errors import InvalidMessageError
from .session_service import SessionApplicationService

# Preserve the old private helper import paths for downstream integrations.
_number = _number_value
_result_status = _result_status_value


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
        self._evaluation_recorder = ChatEvaluationRecorder(evaluation)

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
        except asyncio.CancelledError:
            await self.sessions.mark_run_interrupted(session_id=session_id, run_id=run_id)
            raise
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
                cancellation_latency_ms=(time.perf_counter() - started) * 1000
                if exc.__class__.__name__ == "RunInterrupted"
                else None,
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
        graph_events = self.graph.stream(
            user_id=user_id,
            user_name=user_name,
            session_id=session_id,
            message=message,
            run_id=run_id,
        )
        try:
            async for event in graph_events:
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
            await self.sessions.mark_run_interrupted(session_id=session_id, run_id=run_id)
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
        finally:
            close = getattr(graph_events, "aclose", None)
            if callable(close):
                try:
                    await close()
                except Exception:
                    # A transport disconnect may race with graph cleanup;
                    # preserve the original stream outcome and rely on the
                    # store marker below to invalidate the run.
                    pass
            if not recorded:
                try:
                    await self.sessions.mark_run_interrupted(session_id=session_id, run_id=run_id)
                except Exception:
                    # Disconnect cleanup is best effort and must not mask the
                    # original stream cancellation or provider error.
                    pass

    def _validate(self, message: str) -> str:
        clean = message.strip()
        if not clean:
            raise InvalidMessageError("message must not be empty")
        if len(clean) > self.max_message_length:
            raise InvalidMessageError(f"message exceeds {self.max_message_length} characters")
        return clean

    def _record_result(self, *, user_id: str, message: str, result: ChatResult, elapsed_ms: float) -> None:
        self._evaluation_recorder.evaluation = self.evaluation
        self._evaluation_recorder.record_result(user_id=user_id, message=message, result=result, elapsed_ms=elapsed_ms)

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
        self._evaluation_recorder.evaluation = self.evaluation
        self._evaluation_recorder.record_stream(
            user_id=user_id,
            message=message,
            trace_id=trace_id,
            output=output,
            status=status,
            tools=tools,
            done_data=done_data,
            elapsed_ms=elapsed_ms,
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
        first_event_latency_ms: float | None = None,
        first_visible_latency_ms: float | None = None,
        cancellation_latency_ms: float | None = None,
    ) -> None:
        self._evaluation_recorder.evaluation = self.evaluation
        self._evaluation_recorder.record(
            user_id=user_id,
            message=message,
            output=output,
            status=status,
            trace_id=trace_id,
            tools=tools,
            agent_latency_ms=agent_latency_ms,
            digital_human_latency_ms=digital_human_latency_ms,
            first_event_latency_ms=first_event_latency_ms,
            first_visible_latency_ms=first_visible_latency_ms,
            cancellation_latency_ms=cancellation_latency_ms,
        )
