"""Build the provider-agnostic LangGraph orchestration pipeline."""

from __future__ import annotations

import asyncio
from contextlib import nullcontext
import time
from typing import Any

from langgraph.graph import END, START, StateGraph

from ..agent.intent import CompositeIntentClassifier, IntentClassifier
from ..agent.models import FillerPhase, IntentDecision, ToolRoutePlan
from ..agent.performance import PerformancePlanner
from ..agent.response import build_agent_response
from ..agent.security import assess_prompt_injection, blocked_decision, blocked_plan, safe_refusal
from ..agent.steering import RunToken, should_stop
from ..agent.tool_catalog import ProgressiveToolRouter, ToolRouter
from ..avatar.registry import ProviderRegistry
from ..avatar.presentation import PresentationLayer, ProviderRuntime
from ..domain.models import ToolCallRecord
from ..domain.ports import SessionStore, ToolClient
from ..rag.models import SearchRequest
from .state import AgentGraphState
from .runtime_support import run_with_steering


def build_graph(
    *,
    tool_client: ToolClient,
    providers: ProviderRegistry,
    sessions: SessionStore,
    rag_service: Any | None = None,
    observer: Any | None = None,
    intent_classifier: IntentClassifier | None = None,
    tool_router: ToolRouter | None = None,
    performance: PerformancePlanner | None = None,
    provider_cancel_grace_seconds: float = 0.25,
):
    """Return a compiled graph with all external decisions injected.

    The graph intentionally remains deterministic in v0.1.1.  Replacing the
    classifier or route policy does not change the API or provider adapters.
    """

    classifier = intent_classifier or CompositeIntentClassifier()
    router = tool_router or ProgressiveToolRouter()
    performer = performance or PerformancePlanner()
    presentation = PresentationLayer()

    async def receive(state: AgentGraphState) -> dict[str, Any]:
        attrs = _attrs(state, {"message_length": len(state.get("message", ""))})
        with _span(observer, "langgraph_node", "receive", attrs):
            if await _stopped(sessions, state):
                return {"interrupted": True}
            record = await sessions.get(state["session_id"])
            if record is None:
                return {"error": "session expired or not found"}
            if record.session.user_id != state["user_id"]:
                return {"error": "session does not belong to user"}
            if record.interrupted and not state.get("run_id"):
                return {"interrupted": True}
            if state.get("security_blocked"):
                decision = blocked_decision()
                plan = blocked_plan()
                await sessions.touch(state["session_id"])
                return {
                    "intent": decision.model_dump(mode="json"),
                    "tool_plan": plan.model_dump(mode="json"),
                }
            decision = _decision(state)
            if decision is None:
                decision, cancelled = await run_with_steering(
                    lambda: classifier.classify(
                        state["message"],
                        context={"owner_id": state["user_id"], "session_id": state["session_id"]},
                    ),
                    sessions=sessions,
                    token=_run_token(state),
                    cancel_grace_seconds=provider_cancel_grace_seconds,
                )
                if cancelled or decision is None:
                    return {"interrupted": True}
            plan = _plan(state) or router.route(decision, message=state["message"])
            await sessions.touch(state["session_id"])
            return {
                "intent": decision.model_dump(mode="json"),
                "tool_plan": plan.model_dump(mode="json"),
            }

    async def security_gate(state: AgentGraphState) -> dict[str, Any]:
        """Block obvious instruction/credential exfiltration before routing."""
        attrs = _attrs(state, {"message_length": len(state.get("message", ""))})
        with _span(observer, "langgraph_node", "security_gate", attrs):
            assessment = assess_prompt_injection(state.get("message", ""))
        if assessment.attempted:
            return {"security_blocked": True, "security_reason": assessment.reason_code or "policy"}
        return {"security_blocked": False}

    async def retrieve(state: AgentGraphState) -> dict[str, Any]:
        stopped = await _stopped(sessions, state)
        if stopped:
            return {"rag_hits": [], "interrupted": True}
        if state.get("security_blocked"):
            return {"rag_hits": [], "security_blocked": True}
        if rag_service is None:
            return {"rag_hits": []}
        decision = _decision(state)
        if decision is not None and not decision.requires_retrieval:
            return {"rag_hits": []}
        attrs = _attrs(state, {"query_length": len(state.get("message", ""))})
        with _span(observer, "rag_retrieval", "rag.search", attrs):
            try:
                result, cancelled = await run_with_steering(
                    lambda: rag_service.search(
                        SearchRequest(query=state["message"], collection="default", top_k=3),
                        owner_id=state["user_id"],
                    ),
                    sessions=sessions,
                    token=_run_token(state),
                    cancel_grace_seconds=provider_cancel_grace_seconds,
                )
                if cancelled or result is None:
                    return {"rag_hits": [], "interrupted": True}
            except Exception as exc:
                return {"rag_hits": [], "rag_error": _safe_error(exc)}
        return {"rag_hits": [hit.model_dump(mode="json") for hit in result.hits]}

    async def tool(state: AgentGraphState) -> dict[str, Any]:
        if state.get("security_blocked"):
            return {
                "tool_calls": [],
                "tool_plan": blocked_plan().model_dump(mode="json"),
                "security_blocked": True,
            }
        if await _stopped(sessions, state):
            return {"interrupted": True}
        plan = _plan(state)
        if plan is None:
            decision = _decision(state) or IntentDecision(name="unknown")
            plan = router.route(decision, message=state["message"])
        async def call_one(name: str) -> ToolCallRecord:
            if await _stopped(sessions, state):
                return ToolCallRecord(name=name, error="run interrupted")
            arguments = _tool_arguments(name, state["message"])
            attrs = _attrs(state, {"argument_keys": sorted(arguments), "category": plan.category})
            with _span(observer, "mcp_call", name, attrs):
                try:
                    result, cancelled = await run_with_steering(
                        lambda: tool_client.call(name, arguments),
                        sessions=sessions,
                        token=_run_token(state),
                        cancel_grace_seconds=provider_cancel_grace_seconds,
                    )
                    if cancelled:
                        return ToolCallRecord(name=name, arguments=arguments, error="run interrupted")
                    if result is None:
                        return ToolCallRecord(name=name, arguments=arguments, error="tool returned no result")
                    return result
                except Exception as exc:  # defensive boundary for custom clients
                    return ToolCallRecord(name=name, arguments=arguments, error=_safe_error(exc))

        # Independent MCP probes run concurrently, reducing latency without
        # exposing more tools than the route plan selected.
        calls = list(await asyncio.gather(*(call_one(name) for name in plan.selected_tools)))
        if await _stopped(sessions, state):
            return {
                "tool_calls": calls,
                "interrupted": True,
                "tool_plan": plan.model_dump(mode="json"),
            }
        return {"tool_calls": calls, "tool_plan": plan.model_dump(mode="json")}

    async def respond(state: AgentGraphState) -> dict[str, Any]:
        if state.get("error"):
            return {"reply": "请求未完成，请稍后重试。"}
        if state.get("security_blocked"):
            return {"reply": safe_refusal()}
        if state.get("interrupted") or await _stopped(sessions, state):
            return {"reply": "请求已打断。", "interrupted": True}
        segments = [f"已收到：{state['message']}"]
        hits = state.get("rag_hits", [])
        if hits:
            references = []
            for item in hits[:3]:
                chunk = item.get("chunk", {}) if isinstance(item, dict) else {}
                text = str(chunk.get("text", "")).strip().replace("\n", " ")
                if text:
                    references.append(f"- {text[:180]}")
            if references:
                segments.append("参考资料：\n" + "\n".join(references))
        decision = _decision(state)
        if decision is not None and decision.is_control:
            segments = ["好的，我先停下来。"]
        segments.append("MCP 探针：已完成")
        return {"reply": "\n\n".join(segments)}

    async def provider(state: AgentGraphState) -> dict[str, Any]:
        stopped = await _stopped(sessions, state)
        if state.get("error") or state.get("interrupted") or stopped:
            return {"interrupted": bool(state.get("interrupted") or stopped)}
        record = await sessions.get(state["session_id"])
        if record is None:
            return {"error": "session expired or not found"}
        adapter = providers.get(record.session.provider)
        attrs = _attrs(state, {"text_length": len(state.get("reply", ""))})
        with _span(observer, "provider_event", "send_text", attrs, provider=record.session.provider):
            started = time.perf_counter()
            cue = performer.for_phase(FillerPhase.SPEAKING)
            response = build_agent_response(
                text=state.get("reply", ""),
                trace_id=state.get("trace_id", ""),
                session_id=state["session_id"],
                run_id=state.get("run_id"),
                performance=cue.model_dump(mode="json", by_alias=True),
            )
            try:
                result, cancelled = await run_with_steering(
                    lambda: ProviderRuntime(adapter, presentation).present(response),
                    sessions=sessions,
                    token=_run_token(state),
                    cancel_grace_seconds=provider_cancel_grace_seconds,
                )
                if cancelled or result is None:
                    return {
                        "interrupted": True,
                        "digital_human_latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    }
                # The provider call may outlive a superseding run; suppress
                # its result so stale output cannot complete the old run.
                if await _stopped(sessions, state):
                    return {"interrupted": True, "digital_human_latency_ms": round((time.perf_counter() - started) * 1000, 2)}
                return {
                    "agent_response": response,
                    "provider_result": result,
                    "digital_human_latency_ms": round((time.perf_counter() - started) * 1000, 2),
                }
            except Exception as exc:
                return {
                    "agent_response": response,
                    "provider_error": _safe_error(exc),
                    "digital_human_latency_ms": round((time.perf_counter() - started) * 1000, 2),
                }

    graph = StateGraph(AgentGraphState)
    for name, node in (
        ("security", security_gate),
        ("receive", receive),
        ("retrieve", retrieve),
        ("tool", tool),
        ("respond", respond),
        ("provider", provider),
    ):
        graph.add_node(name, node)
    graph.add_edge(START, "security")
    graph.add_edge("security", "receive")
    graph.add_edge("receive", "retrieve")
    graph.add_edge("retrieve", "tool")
    graph.add_edge("tool", "respond")
    graph.add_edge("respond", "provider")
    graph.add_edge("provider", END)
    return graph.compile()


def _tool_arguments(name: str, message: str) -> dict[str, Any]:
    return {"message": message} if name == "echo" else {}


def _decision(state: AgentGraphState) -> IntentDecision | None:
    value = state.get("intent")
    if not value:
        return None
    return value if isinstance(value, IntentDecision) else IntentDecision.model_validate(value)


def _plan(state: AgentGraphState) -> ToolRoutePlan | None:
    value = state.get("tool_plan")
    if not value:
        return None
    return value if isinstance(value, ToolRoutePlan) else ToolRoutePlan.model_validate(value)


async def _stopped(sessions: SessionStore, state: AgentGraphState) -> bool:
    token = RunToken(session_id=state["session_id"], run_id=state["run_id"]) if state.get("run_id") else None
    return await should_stop(sessions, token)


def _attrs(state: AgentGraphState, values: dict[str, Any]) -> dict[str, Any]:
    return {"owner_id": state.get("user_id", "unknown"), "run_id": state.get("run_id"), **values}


def _span(
    observer: Any | None,
    factory: str,
    name: str,
    attributes: dict[str, Any],
    *,
    provider: str | None = None,
):
    if observer is None:
        return nullcontext()
    method = getattr(observer, factory)
    if factory == "provider_event":
        return method(provider or "unknown", name, attributes=attributes)
    return method(name, attributes=attributes)


def _safe_error(exc: Exception) -> str:
    message = str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__
    return message[:300]


def _run_token(state: AgentGraphState) -> RunToken | None:
    run_id = state.get("run_id")
    if not run_id:
        return None
    return RunToken(session_id=state["session_id"], run_id=run_id)
