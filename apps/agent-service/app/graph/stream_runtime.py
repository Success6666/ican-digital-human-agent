"""Streaming execution for the LangGraph runtime.

The stream is kept separate from graph construction and synchronous invocation
so transport-facing event details do not inflate the lifecycle runtime.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import time
import uuid
from typing import Any

from ..agent.models import FillerPhase, IntentDecision, IntentName, IntentSource
from ..agent.security import assess_prompt_injection, blocked_decision, blocked_plan
from ..agent.steering import RunInterrupted, RunToken, open_run
from ..agent.streaming import filler_payload, result_payload
from .runtime_support import (
    agent_latency,
    ensure_running,
    interruption_latency_ms,
    safe_error,
    trace_scope,
)
from .stream_helpers import elapsed_ms as _elapsed_ms
from .stream_helpers import invalidate_run as _invalidate_run
from .stream_helpers import latency_payload as _latency_payload
from .stream_helpers import node_event as _node_event
from .stream_helpers import response_events as _response_events
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
    if run_id is None:
        run_id = (await open_run(runtime._sessions, session_id)).run_id
    terminal = False
    first_event_latency_ms: float | None = None
    first_visible_latency_ms: float | None = None

    def mark_first_visible() -> None:
        nonlocal first_visible_latency_ms
        if first_visible_latency_ms is not None:
            return
        first_visible_latency_ms = _elapsed_ms(stream_started)
        runtime._record_first_visible(
            trace_id,
            owner_id=user_id,
            latency_ms=first_visible_latency_ms,
        )

    try:
        assessment = assess_prompt_injection(message)
        # Keep the first acknowledgement independent from model classification.
        # A remote classifier can be slow, while this cue is safe, short and
        # interruptible; the later intent event carries the authoritative result.
        provisional = IntentDecision(
            name=IntentName.UNKNOWN,
            confidence=0.0,
            source=IntentSource.FALLBACK,
            rationale="首响占位",
        )
        immediate_filler = runtime._filler.plan(provisional, message=message)
        listening = runtime._performance.for_listening()
        first_event_latency_ms = _elapsed_ms(stream_started)
        runtime._record_first_byte(
            trace_id,
            owner_id=user_id,
            latency_ms=first_event_latency_ms,
        )
        yield {
            "event": "start",
            "data": {
                "traceId": trace_id,
                "sessionId": session_id,
                "runId": run_id,
                "performance": listening.model_dump(mode="json", by_alias=True),
            },
        }
        token = RunToken(session_id=session_id, run_id=run_id) if run_id else None
        await ensure_running(runtime._sessions, token)
        if immediate_filler.should_emit and immediate_filler.text:
            mark_first_visible()
            yield {"event": "filler", "data": filler_payload(trace_id, immediate_filler, run_id=run_id)}
        await ensure_running(runtime._sessions, token)
        if assessment.attempted:
            decision = blocked_decision()
            plan = blocked_plan()
        else:
            decision = await runtime._classify_steered(
                message,
                user_id=user_id,
                session_id=session_id,
                token=token,
            )
            plan = runtime._router.route(decision, message=message)
        await ensure_running(runtime._sessions, token)
        mark_first_visible()
        yield {
            "event": "intent",
            "data": {
                "traceId": trace_id,
                "runId": run_id,
                "intent": "security" if assessment.attempted else decision.name,
                "confidence": decision.confidence,
                "source": decision.source,
            },
        }
        mark_first_visible()
        yield {
            "event": "tool_disclosure",
            "data": {
                "traceId": trace_id,
                "runId": run_id,
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
            trace_id=trace_id,
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
                            run_id=run_id,
                            runtime=runtime,
                        ):
                            # Keep the interruption check between chunks so a
                            # superseding run can stop speech promptly.
                            await ensure_running(runtime._sessions, token)
                            await asyncio.sleep(0)
                            if delta.get("data", {}).get("text"):
                                mark_first_visible()
                            yield delta
                        continue
                    event = _node_event(
                        node_name,
                        payload,
                        trace_id=trace_id,
                        run_id=run_id,
                    )
                    if event is not None:
                        mark_first_visible()
                        yield event
            state["agent_latency_ms"] = agent_latency(
                started_at=stream_started,
                digital_human_latency_ms=state.get("digital_human_latency_ms"),
            )
            state["first_event_latency_ms"] = first_event_latency_ms
            state["first_visible_latency_ms"] = first_visible_latency_ms
            result = runtime._result(state, session_id=session_id, trace_id=trace_id)
            cancellation_latency = None
            if result.interrupted:
                cancellation_latency = await interruption_latency_ms(
                    runtime._sessions,
                    token,
                    consume=True,
                )
                result.cancellation_latency_ms = cancellation_latency
                runtime._record_interrupted(
                    trace_id,
                    owner_id=user_id,
                    reason="graph_interrupted",
                    latency_ms=cancellation_latency,
                )
            done = result_payload(result)
            done.update(
                _latency_payload(
                    first_event_latency_ms,
                    first_visible_latency_ms,
                    cancellation_latency
                    if cancellation_latency is not None
                    else result.cancellation_latency_ms
                )
            )
            done["performance"] = runtime._performance.for_phase(FillerPhase.COMPLETE).model_dump(
                mode="json", by_alias=True
            )
            terminal = True
            yield {"event": "done", "data": done}
    except RunInterrupted:
        terminal = True
        cancellation_latency = await interruption_latency_ms(
            runtime._sessions,
            RunToken(session_id=session_id, run_id=run_id) if run_id else None,
            consume=True,
        )
        if cancellation_latency is None:
            cancellation_latency = _elapsed_ms(stream_started)
        runtime._record_interrupted(
            trace_id,
            owner_id=user_id,
            reason="run_interrupted",
            latency_ms=cancellation_latency,
        )
        cue = runtime._performance.for_phase(FillerPhase.INTERRUPTED)
        yield {
            "event": "interrupted",
            "data": {
                "traceId": trace_id,
                "runId": run_id,
                "message": "请求已打断。",
                "performance": cue.model_dump(mode="json", by_alias=True),
                **_latency_payload(first_event_latency_ms, first_visible_latency_ms, cancellation_latency),
            },
        }
        yield {
            "event": "done",
            "data": {
                "reply": "请求已打断。",
                "traceId": trace_id,
                "sessionId": session_id,
                "runId": run_id,
                "provider": "unknown",
                "toolCalls": [],
                "interrupted": True,
                **_latency_payload(first_event_latency_ms, first_visible_latency_ms, cancellation_latency),
            },
        }
    except asyncio.CancelledError:
        cancellation_latency = await interruption_latency_ms(
            runtime._sessions,
            RunToken(session_id=session_id, run_id=run_id) if run_id else None,
            consume=True,
        )
        if cancellation_latency is None:
            cancellation_latency = _elapsed_ms(stream_started)
        runtime._record_interrupted(
            trace_id,
            owner_id=user_id,
            reason="client_disconnect",
            latency_ms=cancellation_latency,
        )
        raise
    except Exception as exc:
        # An application/transport error is still a terminal stream outcome.
        # Invalidate the run before publishing the terminal frame so a later
        # request cannot observe the failed run as active.
        if run_id:
            await _invalidate_run(runtime, session_id=session_id, run_id=run_id)
        terminal = True
        yield {
            "event": "error",
            "data": {"traceId": trace_id, "runId": run_id, "message": safe_error(exc)},
        }
        yield {
            "event": "done",
            "data": {
                "reply": "请求未完成，请稍后重试。",
                "traceId": trace_id,
                "sessionId": session_id,
                "runId": run_id,
                "provider": "unknown",
                "toolCalls": [],
                "interrupted": False,
                **_latency_payload(first_event_latency_ms, first_visible_latency_ms, None),
            },
        }
    finally:
        if not terminal and run_id:
            await _invalidate_run(runtime, session_id=session_id, run_id=run_id)
