"""Build the provider-agnostic LangGraph orchestration pipeline."""

from __future__ import annotations

import time
from typing import Any

from langgraph.graph import END, START, StateGraph

from ..agent.intent import CompositeIntentClassifier, IntentClassifier
from ..agent.models import FillerPhase, IntentDecision
from ..agent.performance import PerformancePlanner
from ..agent.response import build_agent_response
from ..agent.security import assess_prompt_injection, blocked_decision, blocked_plan, safe_refusal
from ..agent.tool_catalog import ProgressiveToolRouter, ToolRouter
from ..avatar.registry import ProviderRegistry
from ..avatar.presentation import PresentationLayer, ProviderRuntime
from ..domain.models import ToolCallRecord
from ..domain.ports import SessionStore, ToolClient
from ..llm.client import LlmClient
from ..rag.models import SearchRequest
from .concurrency import bounded_map
from .builder_support import attrs as _attrs
from .builder_support import decision_from_state as _decision
from .builder_support import plan_from_state as _plan
from .builder_support import run_token as _run_token
from .builder_support import safe_error as _safe_error
from .builder_support import span_context as _span
from .builder_support import stopped as _stopped
from .builder_support import tool_arguments as _tool_arguments
from .runtime_support import run_with_steering
from .state import AgentGraphState


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
    max_parallel_tools: int = 4,
    llm_client: LlmClient | None = None,
):
    """Return a compiled graph with all external decisions injected.

    The graph intentionally remains deterministic in v0.1.3.  Replacing the
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
        # exposing more tools than the route plan selected. A bounded worker
        # pool prevents a custom route plan from creating an unbounded task
        # set, and retains deterministic input order for the stream.
        calls = await bounded_map(plan.selected_tools, call_one, limit=max_parallel_tools)
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
        hits = state.get("rag_hits", [])
        context_texts: list[str] = []
        if hits:
            references = []
            for item in hits[:3]:
                chunk = item.get("chunk", {}) if isinstance(item, dict) else {}
                text = str(chunk.get("text", "")).strip().replace("\n", " ")
                if text:
                    references.append(f"- {text[:180]}")
                    context_texts.append(text[:180])
            if references:
                context_texts = context_texts[:3]
        decision = _decision(state)
        if decision is not None and decision.is_control:
            return {"reply": "好的，我先停下来。"}
        if llm_client is not None and getattr(llm_client, "enabled", False):
            try:
                return {"reply": await llm_client.complete(message=state["message"], context=context_texts)}
            except Exception as exc:
                return {"reply": f"已收到：{state['message']}\n\n当前模型暂不可用，已切换安全回退。", "llm_error": _safe_error(exc)}
        segments = [f"已收到：{state['message']}"]
        if context_texts:
            segments.append("参考资料：\n" + "\n".join(f"- {item}" for item in context_texts))
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
                provider_status = str(getattr(result, "status", "ok") or "ok").casefold()
                if provider_status in {"interrupted", "cancelled", "canceled"}:
                    return {
                        "provider_result": result,
                        "interrupted": True,
                        "digital_human_latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    }
                if provider_status in {"error", "failed"}:
                    return {
                        "agent_response": response,
                        "provider_result": result,
                        "provider_error": "provider returned an error",
                        "digital_human_latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    }
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
