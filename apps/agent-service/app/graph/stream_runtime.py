"""Streaming execution for the LangGraph runtime.

The stream is kept separate from graph construction and synchronous invocation
so transport-facing event details do not inflate the lifecycle runtime.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
import time
import uuid
from typing import Any

from ..agent.models import FillerPhase
from ..agent.security import assess_prompt_injection, blocked_decision, blocked_plan, reason_label
from ..agent.steering import RunInterrupted, RunToken, open_run
from ..agent.streaming import chunks, dump_tools, filler_payload, provider_performance, result_payload
from .runtime_support import agent_latency, ensure_running, safe_error, trace_scope
from .state import AgentGraphState


async def stream_runtime(
    runtime: Any,
    *,
    user_id: str,
    user_name: str,
    session_id: str,
    message: str,
    run_id: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Yield user-facing stream events while preserving run interruption checks."""
    trace_id = uuid.uuid4().hex
    stream_started = time.perf_counter()
    listening = runtime._performance.for_listening()
    yield {
        "event": "start",
        "data": {
            "traceId": trace_id,
            "sessionId": session_id,
            "performance": listening.model_dump(mode="json", by_alias=True),
        },
    }
    try:
        if run_id is None:
            run_id = (await open_run(runtime._sessions, session_id)).run_id
        token = RunToken(session_id=session_id, run_id=run_id) if run_id else None
        assessment = assess_prompt_injection(message)
        if assessment.attempted:
            decision = blocked_decision()
            plan = blocked_plan()
        else:
            decision = await runtime._classify(message, user_id=user_id, session_id=session_id)
            plan = runtime._router.route(decision, message=message)
        filler = runtime._filler.plan(decision, message=message)
        await ensure_running(runtime._sessions, token)
        runtime._record_first_byte(
            trace_id,
            owner_id=user_id,
            latency_ms=(time.perf_counter() - stream_started) * 1000,
        )
        # The acknowledgement is intentionally a separate event. Existing
        # clients ignore unknown events while new clients can speak it fast.
        if filler.should_emit and filler.text:
            yield {"event": "filler", "data": filler_payload(trace_id, filler)}
        yield {
            "event": "intent",
            "data": {
                "traceId": trace_id,
                "intent": "security" if assessment.attempted else decision.name,
                "confidence": decision.confidence,
                "source": decision.source,
            },
        }
        yield {
            "event": "tool_disclosure",
            "data": {
                "traceId": trace_id,
                "level": plan.disclosure_level,
                "category": plan.category,
                "tools": [
                    {"name": item.name, "label": item.label, "description": item.description}
                    for item in plan.disclosed_tools
                ],
            },
        }
        state: AgentGraphState = {
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
        async with trace_scope(
            runtime._observer,
            "agent.stream",
            {"owner_id": user_id, "run_id": run_id, "message_length": len(message)},
        ):
            async for update in runtime._graph.astream(state, stream_mode="updates"):
                await ensure_running(runtime._sessions, token)
                if not isinstance(update, dict):
                    continue
                for node_name, payload in update.items():
                    if not isinstance(payload, dict):
                        continue
                    state.update(payload)
                    if node_name == "respond":
                        for delta in _response_events(
                            payload,
                            trace_id=trace_id,
                            runtime=runtime,
                        ):
                            # Keep the interruption check between chunks so a
                            # superseding run can stop speech promptly.
                            await ensure_running(runtime._sessions, token)
                            await asyncio.sleep(0)
                            yield delta
                        continue
                    event = _node_event(
                        node_name,
                        payload,
                        trace_id=trace_id,
                    )
                    if event is not None:
                        yield event
            state["agent_latency_ms"] = agent_latency(
                started_at=stream_started,
                digital_human_latency_ms=state.get("digital_human_latency_ms"),
            )
            result = runtime._result(state, session_id=session_id, trace_id=trace_id)
            done = result_payload(result)
            done["performance"] = runtime._performance.for_phase(FillerPhase.COMPLETE).model_dump(
                mode="json", by_alias=True
            )
            yield {"event": "done", "data": done}
    except RunInterrupted:
        cue = runtime._performance.for_phase(FillerPhase.INTERRUPTED)
        yield {
            "event": "interrupted",
            "data": {
                "traceId": trace_id,
                "message": "请求已打断。",
                "performance": cue.model_dump(mode="json", by_alias=True),
            },
        }
        yield {
            "event": "done",
            "data": {
                "reply": "请求已打断。",
                "traceId": trace_id,
                "sessionId": session_id,
                "provider": "unknown",
                "toolCalls": [],
                "interrupted": True,
            },
        }
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        yield {"event": "error", "data": {"traceId": trace_id, "message": safe_error(exc)}}


def _node_event(
    node_name: str,
    payload: dict[str, Any],
    *,
    trace_id: str,
) -> dict[str, Any] | None:
    """Translate a graph update into a transport event, if applicable."""
    if node_name == "retrieve":
        if payload.get("security_blocked"):
            return None
        return {
            "event": "rag",
            "data": {
                "traceId": trace_id,
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
                "blocked": blocked,
                "reason": reason_label(payload.get("security_reason")) if blocked else None,
            },
        }
    if node_name == "tool":
        if payload.get("security_blocked"):
            return None
        return {
            "event": "tool",
            "data": {"traceId": trace_id, "toolCalls": dump_tools(payload.get("tool_calls", []))},
        }
    if node_name == "provider":
        return {
            "event": "provider",
            "data": {
                "traceId": trace_id,
                "status": "error" if payload.get("provider_error") else "ok",
                "message": payload.get("provider_error"),
                "performance": provider_performance(payload),
            },
        }
    return None


def _response_events(
    payload: dict[str, Any],
    *,
    trace_id: str,
    runtime: Any,
) -> Iterator[dict[str, Any]]:
    """Build response deltas lazily; the caller performs async checks."""
    reply = str(payload.get("reply", ""))
    for index, chunk in enumerate(chunks(reply)):
        data: dict[str, Any] = {"traceId": trace_id, "text": chunk}
        if index == 0:
            data["performance"] = runtime._performance.for_phase(FillerPhase.SPEAKING).model_dump(
                mode="json", by_alias=True
            )
        yield {"event": "delta", "data": data}
