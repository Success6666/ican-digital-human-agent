"""Execute project evaluation datasets through the real Agent graph."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import time
from typing import Any

from ..application.session_service import SessionApplicationService
from ..graph.runtime import AgentGraphRuntime
from .metrics import looks_like_safe_refusal
from .models import DatasetRunRequest, EvaluationCase, EvaluationRun, EvaluationRunRequest
from .service import EvaluationService


@dataclass(slots=True)
class _Execution:
    output: str
    status: str
    trace_id: str | None
    tools: list[str]
    evidence: list[str]
    agent_latency_ms: float | None
    digital_human_latency_ms: float | None
    first_event_latency_ms: float | None
    first_visible_latency_ms: float | None
    cancellation_latency_ms: float | None
    error: str | None = None


class EvaluationDatasetRunner:
    def __init__(
        self,
        *,
        service: EvaluationService,
        graph: AgentGraphRuntime,
        sessions: SessionApplicationService,
    ) -> None:
        self.service = service
        self.graph = graph
        self.sessions = sessions

    async def run(
        self,
        dataset_id: str,
        request: DatasetRunRequest,
        *,
        owner_id: str,
        user_name: str,
    ) -> dict[str, Any]:
        dataset = self.service.dataset(dataset_id)
        if dataset is None:
            raise KeyError(dataset_id)
        requested = set(request.case_ids)
        cases = [case for case in dataset.cases if not requested or case.id in requested]
        missing = requested - {case.id for case in cases}
        if missing:
            raise ValueError(f"unknown case ids: {', '.join(sorted(missing))}")
        semaphore = asyncio.Semaphore(request.concurrency)

        async def execute(case: EvaluationCase) -> list[EvaluationRun]:
            async with semaphore:
                repeat = max(request.repeat, 2 if "一致性" in case.tags else 1)
                attempts = [
                    await self._execute_case(
                        case,
                        owner_id=owner_id,
                        user_name=user_name,
                        timeout_seconds=request.timeout_seconds,
                    )
                    for _ in range(repeat)
                ]
                return [
                    self._record(dataset_id, case, attempt, owner_id=owner_id, comparisons=[
                        item.output for offset, item in enumerate(attempts) if offset != index and item.output
                    ])
                    for index, attempt in enumerate(attempts)
                ]

        grouped = await asyncio.gather(*(execute(case) for case in cases))
        runs = [run for items in grouped for run in items]
        statuses: dict[str, int] = {}
        for run in runs:
            statuses[run.status] = statuses.get(run.status, 0) + 1
        return {
            "dataset_id": dataset.id,
            "dataset_name": dataset.name,
            "case_count": len(cases),
            "run_count": len(runs),
            "statuses": statuses,
            "run_ids": [run.id for run in runs],
        }

    async def _execute_case(
        self,
        case: EvaluationCase,
        *,
        owner_id: str,
        user_name: str,
        timeout_seconds: float,
    ) -> _Execution:
        session_id: str | None = None
        started = time.perf_counter()
        try:
            session = await self.sessions.create(user_id=owner_id, provider_name="mock")
            session_id = session.session_id
            run_id = await self.sessions.begin_run(user_id=owner_id, session_id=session_id)
            result = await asyncio.wait_for(
                self.graph.invoke(
                    user_id=owner_id,
                    user_name=user_name,
                    session_id=session_id,
                    message=case.prompt,
                    run_id=run_id,
                ),
                timeout=timeout_seconds,
            )
            status = "interrupted" if result.interrupted else "success"
            if case.injection_attempt and looks_like_safe_refusal(result.reply):
                status = "blocked"
            return _Execution(
                output=result.reply,
                status=status,
                trace_id=result.trace_id,
                tools=sorted({call.name for call in result.tool_calls}),
                evidence=_tool_evidence(result.tool_calls),
                agent_latency_ms=result.agent_latency_ms or _elapsed_ms(started),
                digital_human_latency_ms=result.digital_human_latency_ms,
                first_event_latency_ms=result.first_event_latency_ms,
                first_visible_latency_ms=result.first_visible_latency_ms,
                cancellation_latency_ms=result.cancellation_latency_ms,
            )
        except asyncio.TimeoutError:
            return _Execution("", "error", None, [], [], _elapsed_ms(started), None, None, None, None, "case timeout")
        except Exception as exc:
            return _Execution("", "error", None, [], [], _elapsed_ms(started), None, None, None, None, exc.__class__.__name__)
        finally:
            if session_id:
                try:
                    await self.sessions.close(user_id=owner_id, session_id=session_id)
                except Exception:
                    pass

    def _record(
        self,
        dataset_id: str,
        case: EvaluationCase,
        execution: _Execution,
        *,
        owner_id: str,
        comparisons: list[str],
    ) -> EvaluationRun:
        blocked = case.injection_attempt and looks_like_safe_refusal(execution.output)
        return self.service.record(
            EvaluationRunRequest(
                dataset_id=dataset_id,
                case_id=case.id,
                trace_id=execution.trace_id,
                input_text=case.prompt,
                output_text=execution.output,
                status=execution.status,
                task_success=execution.status == "success" or (case.expected_blocked and blocked),
                actual_tools=execution.tools,
                evidence=execution.evidence,
                injection_attempt=case.injection_attempt,
                injection_blocked=blocked if case.injection_attempt else None,
                comparison_outputs=comparisons,
                agent_latency_ms=execution.agent_latency_ms,
                digital_human_latency_ms=execution.digital_human_latency_ms,
                first_event_latency_ms=execution.first_event_latency_ms,
                first_visible_latency_ms=execution.first_visible_latency_ms,
                cancellation_latency_ms=execution.cancellation_latency_ms,
                metadata={"runner": "agent_graph", "error": execution.error},
            ),
            owner_id=owner_id,
        )


def _tool_evidence(calls: list[Any]) -> list[str]:
    evidence: list[str] = []
    for call in calls:
        result = getattr(call, "result", None)
        if result is None:
            continue
        try:
            text = json.dumps(result, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(result)
        evidence.append(text[:1000])
    return evidence[:20]


def _elapsed_ms(started: float) -> float:
    return round(max(0.0, (time.perf_counter() - started) * 1000), 2)


__all__ = ["EvaluationDatasetRunner"]
