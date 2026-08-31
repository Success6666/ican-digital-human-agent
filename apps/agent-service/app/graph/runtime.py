"""Application-facing LangGraph runtime with responsive, steerable streaming."""

from __future__ import annotations

from collections.abc import AsyncIterator
import time
import uuid
from typing import Any

from ..agent.intent import CompositeIntentClassifier, IntentClassifier
from ..agent.latency import AdaptiveFillerPolicy, FillerPolicy
from ..agent.models import FillerPhase, IntentDecision
from ..agent.performance import PerformancePlanner
from ..agent.security import assess_prompt_injection, blocked_decision, blocked_plan
from ..agent.steering import RunInterrupted, RunToken, open_run
from ..agent.tool_catalog import ProgressiveToolRouter, ToolRouter
from ..avatar.registry import ProviderRegistry
from ..domain.models import AgentResponse, ChatResult
from ..domain.ports import SessionStore, ToolClient
from ..llm.client import LlmClient
from ..messaging import ReliableMessageBus
from .builder import build_graph
from .runtime_support import agent_latency as _agent_latency
from .runtime_support import ensure_running as _ensure_running
from .runtime_support import interruption_latency_ms as _interruption_latency_ms
from .runtime_support import run_with_steering as _run_with_steering
from .runtime_support import trace_scope as _trace_scope
from .state import AgentGraphState
from .stream_runtime import stream_runtime
from .telemetry import record_first_byte as _record_first_byte
from .telemetry import record_first_visible as _record_first_visible
from .telemetry import record_interrupted as _record_interrupted
from .telemetry import record_marker as _record_marker
from .telemetry import record_observer_event as _record_observer_event


class AgentGraphRuntime:
    def __init__(
        self,
        *,
        tool_client: ToolClient,
        providers: ProviderRegistry,
        sessions: SessionStore,
        rag_service: Any | None = None,
        observer: Any | None = None,
        intent_classifier: IntentClassifier | None = None,
        tool_router: ToolRouter | None = None,
        filler_policy: FillerPolicy | None = None,
        performance: PerformancePlanner | None = None,
        provider_cancel_grace_seconds: float = 0.25,
        max_parallel_tools: int = 4,
        llm_client: LlmClient | None = None,
        message_bus: ReliableMessageBus | None = None,
    ) -> None:
        self._observer = observer
        self._sessions = sessions
        self._classifier = intent_classifier or CompositeIntentClassifier()
        self._router = tool_router or ProgressiveToolRouter()
        self._filler = filler_policy or AdaptiveFillerPolicy(planner=performance)
        self._performance = performance or PerformancePlanner()
        self._cancel_grace_seconds = provider_cancel_grace_seconds
        self._graph = build_graph(
            tool_client=tool_client,
            providers=providers,
            sessions=sessions,
            rag_service=rag_service,
            observer=observer,
            intent_classifier=self._classifier,
            tool_router=self._router,
            performance=self._performance,
            provider_cancel_grace_seconds=provider_cancel_grace_seconds,
            max_parallel_tools=max_parallel_tools,
            llm_client=llm_client,
            message_bus=message_bus,
        )

    async def invoke(
        self,
        *,
        user_id: str,
        user_name: str,
        session_id: str,
        message: str,
        run_id: str | None = None,
    ) -> ChatResult:
        started = time.perf_counter()
        trace_id = uuid.uuid4().hex
        if run_id is None:
            run_id = (await open_run(self._sessions, session_id)).run_id
        token = RunToken(session_id=session_id, run_id=run_id) if run_id else None
        try:
            async with _trace_scope(
                self._observer,
                "agent.invoke",
                {"owner_id": user_id, "run_id": run_id, "message_length": len(message)},
                trace_id=trace_id,
            ):
                assessment = assess_prompt_injection(message)
                if assessment.attempted:
                    decision = blocked_decision()
                    plan = blocked_plan()
                else:
                    decision = await self._classify_steered(
                        message,
                        user_id=user_id,
                        session_id=session_id,
                        token=token,
                    )
                    plan = self._router.route(decision, message=message)
                await _ensure_running(self._sessions, token)
                state = await self._graph.ainvoke(
                    {
                        "user_id": user_id,
                        "user_name": user_name,
                        "session_id": session_id,
                        "message": message,
                        "trace_id": trace_id,
                        "run_id": run_id or "",
                        "intent": decision.model_dump(mode="json"),
                        "tool_plan": plan.model_dump(mode="json"),
                        "security_blocked": assessment.attempted,
                        "security_reason": assessment.reason_code or "",
                    }
                )
                state["agent_latency_ms"] = _agent_latency(
                    started_at=started,
                    digital_human_latency_ms=state.get("digital_human_latency_ms"),
                )
            return self._result(state, session_id=session_id, trace_id=trace_id)
        except RunInterrupted:
            # A synchronous caller can race with a newer run just like an SSE
            # caller. Return a terminal domain result instead of leaking a 500.
            cancellation_latency = await _interruption_latency_ms(
                self._sessions,
                token,
                consume=True,
            )
            self._record_interrupted(
                trace_id,
                owner_id=user_id,
                reason="run_interrupted",
                latency_ms=cancellation_latency,
            )
            return ChatResult(
                reply="请求已打断。",
                trace_id=trace_id,
                session_id=session_id,
                run_id=run_id,
                provider="unknown",
                agent_latency_ms=round((time.perf_counter() - started) * 1000, 2),
                cancellation_latency_ms=cancellation_latency,
                interrupted=True,
                agent_response=AgentResponse(
                    text="请求已打断。",
                    traceId=trace_id,
                    sessionId=session_id,
                    runId=run_id,
                    performance=self._performance.for_phase(FillerPhase.INTERRUPTED).model_dump(
                        mode="json", by_alias=True
                    ),
                ),
            )

    async def stream(
        self,
        *,
        user_id: str,
        user_name: str,
        session_id: str,
        message: str,
        run_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        inner = stream_runtime(
            self,
            user_id=user_id,
            user_name=user_name,
            session_id=session_id,
            message=message,
            run_id=run_id,
        )
        try:
            async for event in inner:
                yield event
        finally:
            try:
                await inner.aclose()
            except Exception:
                # The inner generator already performs best-effort run
                # invalidation; an adapter close failure must not mask the
                # caller's cancellation or completed stream.
                pass

    async def _classify(self, message: str, *, user_id: str, session_id: str) -> IntentDecision:
        return await self._classifier.classify(
            message,
            context={"owner_id": user_id, "session_id": session_id},
        )

    async def _classify_steered(
        self,
        message: str,
        *,
        user_id: str,
        session_id: str,
        token: RunToken | None,
    ) -> IntentDecision:
        result, cancelled = await _run_with_steering(
            lambda: self._classify(message, user_id=user_id, session_id=session_id),
            sessions=self._sessions,
            token=token,
            cancel_grace_seconds=self._cancel_grace_seconds,
        )
        if cancelled or result is None:
            raise RunInterrupted("run interrupted or superseded")
        return result

    def _record_first_byte(self, trace_id: str, *, owner_id: str, latency_ms: float) -> None:
        _record_first_byte(self._observer, trace_id, owner_id=owner_id, latency_ms=latency_ms)

    def _record_first_visible(self, trace_id: str, *, owner_id: str, latency_ms: float) -> None:
        _record_first_visible(self._observer, trace_id, owner_id=owner_id, latency_ms=latency_ms)

    def _record_interrupted(
        self,
        trace_id: str,
        *,
        owner_id: str,
        reason: str,
        latency_ms: float | None = None,
    ) -> None:
        _record_interrupted(
            self._observer,
            trace_id,
            owner_id=owner_id,
            reason=reason,
            latency_ms=latency_ms,
        )

    def _record_marker(self, name: str, *, trace_id: str, owner_id: str, latency_ms: float) -> None:
        _record_marker(self._observer, name, trace_id=trace_id, owner_id=owner_id, latency_ms=latency_ms)

    def _record_observer_event(
        self,
        name: str,
        *,
        trace_id: str,
        event_type: str,
        attributes: dict[str, Any],
    ) -> None:
        _record_observer_event(
            self._observer,
            name,
            trace_id=trace_id,
            event_type=event_type,
            attributes=attributes,
        )

    @staticmethod
    def _result(state: AgentGraphState, *, session_id: str, trace_id: str) -> ChatResult:
        provider_result = state.get("provider_result")
        provider_status_value = (
            provider_result.get("status")
            if isinstance(provider_result, dict)
            else getattr(provider_result, "status", "ok")
        )
        provider_name = (
            provider_result.get("provider")
            if isinstance(provider_result, dict)
            else getattr(provider_result, "provider", None)
        )
        provider_status = str(provider_status_value or "ok").casefold()
        provider_failed = provider_status in {"error", "failed"} or bool(state.get("provider_error"))
        provider = "unknown" if provider_failed or not provider_result or not provider_name else str(provider_name)
        interrupted = bool(state.get("interrupted")) or provider_status in {"interrupted", "cancelled", "canceled"}
        return ChatResult(
            reply=state.get("reply", "请求未完成，请稍后重试。"),
            trace_id=trace_id,
            session_id=session_id,
            run_id=state.get("run_id"),
            provider=provider,
            tool_calls=state.get("tool_calls", []),
            agent_latency_ms=state.get("agent_latency_ms"),
            digital_human_latency_ms=state.get("digital_human_latency_ms"),
            first_event_latency_ms=state.get("first_event_latency_ms"),
            first_visible_latency_ms=state.get("first_visible_latency_ms"),
            cancellation_latency_ms=state.get("cancellation_latency_ms"),
            interrupted=interrupted,
            agent_response=_agent_response(state, session_id=session_id, trace_id=trace_id),
        )


def _agent_response(state: AgentGraphState, *, session_id: str, trace_id: str) -> AgentResponse:
    value = state.get("agent_response")
    if isinstance(value, AgentResponse):
        return value
    if isinstance(value, dict):
        return AgentResponse.model_validate(value)
    return AgentResponse(
        text=str(state.get("reply", "")),
        traceId=trace_id,
        sessionId=session_id,
        runId=state.get("run_id"),
    )
