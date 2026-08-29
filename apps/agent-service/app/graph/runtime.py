"""Application-facing LangGraph runtime with responsive, steerable streaming."""

from __future__ import annotations

from collections.abc import AsyncIterator
import time
import uuid
from typing import Any

from ..agent.intent import CompositeIntentClassifier, IntentClassifier
from ..agent.latency import AdaptiveFillerPolicy, FillerPolicy
from ..agent.models import IntentDecision
from ..agent.performance import PerformancePlanner
from ..agent.security import assess_prompt_injection, blocked_decision, blocked_plan
from ..agent.steering import RunToken, open_run
from ..agent.tool_catalog import ProgressiveToolRouter, ToolRouter
from ..avatar.registry import ProviderRegistry
from ..domain.models import ChatResult
from ..domain.ports import SessionStore, ToolClient
from .builder import build_graph
from .runtime_support import agent_latency as _agent_latency
from .runtime_support import ensure_running as _ensure_running
from .runtime_support import trace_scope as _trace_scope
from .state import AgentGraphState
from .stream_runtime import stream_runtime


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
    ) -> None:
        self._observer = observer
        self._sessions = sessions
        self._classifier = intent_classifier or CompositeIntentClassifier()
        self._router = tool_router or ProgressiveToolRouter()
        self._filler = filler_policy or AdaptiveFillerPolicy(planner=performance)
        self._performance = performance or PerformancePlanner()
        self._graph = build_graph(
            tool_client=tool_client,
            providers=providers,
            sessions=sessions,
            rag_service=rag_service,
            observer=observer,
            intent_classifier=self._classifier,
            tool_router=self._router,
            performance=self._performance,
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
        async with _trace_scope(
            self._observer,
            "agent.invoke",
            {"owner_id": user_id, "run_id": run_id, "message_length": len(message)},
        ):
            assessment = assess_prompt_injection(message)
            if assessment.attempted:
                decision = blocked_decision()
                plan = blocked_plan()
            else:
                decision = await self._classify(message, user_id=user_id, session_id=session_id)
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

    async def stream(
        self,
        *,
        user_id: str,
        user_name: str,
        session_id: str,
        message: str,
        run_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        async for event in stream_runtime(
            self,
            user_id=user_id,
            user_name=user_name,
            session_id=session_id,
            message=message,
            run_id=run_id,
        ):
            yield event

    async def _classify(self, message: str, *, user_id: str, session_id: str) -> IntentDecision:
        return await self._classifier.classify(
            message,
            context={"owner_id": user_id, "session_id": session_id},
        )

    def _record_first_byte(self, trace_id: str, *, owner_id: str, latency_ms: float) -> None:
        if self._observer is None:
            return
        recorder = getattr(self._observer, "record_event", None)
        if callable(recorder):
            recorder(
                "agent.first_byte",
                event_type="latency",
                trace_id=trace_id,
                attributes={"owner_id": owner_id, "latency_ms": round(latency_ms, 2)},
            )

    @staticmethod
    def _result(state: AgentGraphState, *, session_id: str, trace_id: str) -> ChatResult:
        provider_result = state.get("provider_result")
        provider = provider_result.provider if provider_result else "unknown"
        return ChatResult(
            reply=state.get("reply", "请求未完成，请稍后重试。"),
            trace_id=trace_id,
            session_id=session_id,
            provider=provider,
            tool_calls=state.get("tool_calls", []),
            agent_latency_ms=state.get("agent_latency_ms"),
            digital_human_latency_ms=state.get("digital_human_latency_ms"),
            interrupted=bool(state.get("interrupted")),
        )
