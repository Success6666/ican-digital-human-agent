"""Bounded, ordered SSE framing for the chat stream."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request

_STREAM_EVENTS = frozenset(
    {
        "start",
        "filler",
        "security",
        "intent",
        "tool_disclosure",
        "rag",
        "tool",
        "delta",
        "provider",
        "interrupted",
        "done",
        "error",
    }
)
_TERMINAL_STREAM_EVENTS = frozenset({"done"})
_PRE_TERMINAL_EVENTS = frozenset({"error", "interrupted"})
_MAX_SSE_EVENT_BYTES = 256 * 1024
_MAX_SOURCE_EVENT_IDS = 512


async def iter_sse_frames(
    events: AsyncIterator[dict[str, Any]],
    request: Request,
    *,
    session_id: str,
) -> AsyncIterator[str]:
    """Frame graph events while preserving order and cancellation semantics.

    The generator yields one frame at a time, so ASGI's send boundary applies
    natural backpressure. A disconnect closes the source iterator immediately
    and therefore reaches the graph/provider cleanup path.
    """
    sequence = 0
    terminal = False
    error_seen = False
    interrupted_seen = False
    closing = False
    trace_id = "stream"
    run_id: str | None = None
    source_event_ids: set[str] = set()
    try:
        async for event in events:
            if await _client_disconnected(request) or terminal:
                break
            normalized = _normalize_stream_event(event, trace_id=trace_id, run_id=run_id)
            if normalized is None:
                continue
            event_name, data_payload, trace_id, run_id = normalized
            if closing and event_name not in _TERMINAL_STREAM_EVENTS:
                # Error/interruption is followed by the authoritative done
                # frame; discard any provider or tool events that arrive late.
                continue
            source_id = _source_event_id(data_payload)
            if source_id is not None:
                if source_id in source_event_ids:
                    continue
                source_event_ids.add(source_id)
                if len(source_event_ids) > _MAX_SOURCE_EVENT_IDS:
                    source_event_ids.pop()
            sequence += 1
            was_terminal = event_name in _TERMINAL_STREAM_EVENTS
            was_interrupted = event_name == "interrupted"
            payload_interrupted = bool(data_payload.get("interrupted")) or was_interrupted or interrupted_seen
            data_payload["traceId"] = trace_id
            if run_id is not None:
                data_payload["runId"] = run_id
            data_payload["seq"] = sequence
            # Always assign the server sequence. Upstream adapters must not be
            # able to duplicate an event id or forge ordering.
            data_payload["eventId"] = f"{trace_id}:{sequence}"
            data = json.dumps(data_payload, ensure_ascii=False, separators=(",", ":"), default=str)
            if len(data.encode("utf-8")) > _MAX_SSE_EVENT_BYTES:
                event_name = "done" if was_terminal else event_name if event_name in _PRE_TERMINAL_EVENTS else "error"
                data_payload = _oversize_payload(
                    trace_id=trace_id,
                    run_id=run_id,
                    sequence=sequence,
                    session_id=session_id,
                    terminal=was_terminal,
                    interrupted=payload_interrupted,
                )
                data = json.dumps(data_payload, ensure_ascii=False, separators=(",", ":"))
            if event_name in _TERMINAL_STREAM_EVENTS:
                terminal = True
            elif event_name in _PRE_TERMINAL_EVENTS:
                closing = True
            if event_name == "error":
                error_seen = True
            if payload_interrupted:
                # Some adapters report a cancellation through an error or
                # terminal payload instead of a dedicated interrupted event.
                # Preserve that semantic when we synthesize the final frame.
                interrupted_seen = True
            yield f"id:{trace_id}:{sequence}\nevent:{event_name}\ndata:{data}\n\n"
            # Give a superseding request a scheduling opportunity even when a
            # custom graph emits many small events without I/O between them.
            await asyncio.sleep(0)
        # A well-behaved source emits ``done`` itself. If it ends after an
        # error/interruption (or unexpectedly without either), close the wire
        # contract here so clients never wait forever for a terminal frame.
        if not terminal and not await _client_disconnected(request):
            if not closing:
                sequence += 1
                error_payload = _error_payload(trace_id=trace_id, run_id=run_id, sequence=sequence)
                data = json.dumps(error_payload, ensure_ascii=False, separators=(",", ":"))
                yield f"id:{trace_id}:{sequence}\nevent:error\ndata:{data}\n\n"
                error_seen = True
                closing = True
            terminal = True
            sequence += 1
            done_payload = _done_payload(
                trace_id=trace_id,
                run_id=run_id,
                session_id=session_id,
                sequence=sequence,
                interrupted=interrupted_seen,
            )
            data = json.dumps(done_payload, ensure_ascii=False, separators=(",", ":"))
            yield f"id:{trace_id}:{sequence}\nevent:done\ndata:{data}\n\n"
    except asyncio.CancelledError:
        raise
    except Exception:
        # The graph normally emits its own error event. This final guard keeps
        # transport/serialization failures machine-readable without exposing
        # SDK stack traces or terminating with a broken frame.
        if not terminal and not await _client_disconnected(request):
            if not error_seen and not closing:
                sequence += 1
                error_payload = _error_payload(trace_id=trace_id, run_id=run_id, sequence=sequence)
                data = json.dumps(error_payload, ensure_ascii=False, separators=(",", ":"))
                yield f"id:{trace_id}:{sequence}\nevent:error\ndata:{data}\n\n"
                closing = True
            terminal = True
            sequence += 1
            done_payload = _done_payload(
                trace_id=trace_id,
                run_id=run_id,
                session_id=session_id,
                sequence=sequence,
                interrupted=interrupted_seen,
            )
            data = json.dumps(done_payload, ensure_ascii=False, separators=(",", ":"))
            yield f"id:{trace_id}:{sequence}\nevent:done\ndata:{data}\n\n"
    finally:
        close = getattr(events, "aclose", None)
        if callable(close):
            # Closing an already-disconnected async iterator is best effort and
            # must not turn a completed response into another transport failure.
            with contextlib.suppress(Exception):
                await close()


def _normalize_stream_event(
    event: Any,
    *,
    trace_id: str,
    run_id: str | None,
) -> tuple[str, dict[str, Any], str, str | None] | None:
    """Validate one graph event before it reaches the browser transport."""
    if not isinstance(event, dict):
        return None
    event_name = str(event.get("event") or "message").strip().lower()
    if event_name not in _STREAM_EVENTS:
        event_name = "message"
    raw_payload = event.get("data", {})
    data_payload = dict(raw_payload) if isinstance(raw_payload, dict) else {"value": raw_payload}
    event_trace = _safe_sse_value(data_payload.get("traceId"))
    if trace_id != "stream" and event_trace not in {None, trace_id}:
        # The wire trace is fixed by the first valid graph event. A malformed
        # late payload must not move subsequent sequence numbers to another
        # trace or contaminate replay ownership.
        return None
    event_trace = event_trace or trace_id
    event_run = _safe_sse_value(data_payload.get("runId"))
    # A graph stream is bound to one run. Drop a malformed late event rather
    # than allowing it to overwrite the active turn in the client.
    if run_id is not None and event_run is not None and event_run != run_id:
        return None
    return event_name, data_payload, event_trace, event_run or run_id


def _source_event_id(payload: dict[str, Any]) -> str | None:
    value = payload.get("eventId", payload.get("event_id"))
    return _safe_sse_value(value)


def _oversize_payload(
    *,
    trace_id: str,
    run_id: str | None,
    sequence: int,
    session_id: str,
    terminal: bool,
    interrupted: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "traceId": trace_id,
        "runId": run_id,
        "message": "事件内容过大，已省略。",
        "seq": sequence,
        "eventId": f"{trace_id}:{sequence}",
    }
    if terminal:
        payload.update(
            {
                "reply": "请求已打断。" if interrupted else "请求未完成，请稍后重试。",
                "sessionId": session_id,
                "provider": "unknown",
                "toolCalls": [],
                "interrupted": interrupted,
            }
        )
    elif interrupted:
        payload.update({"message": "请求已打断。", "interrupted": True})
    return payload


def _done_payload(
    *,
    trace_id: str,
    run_id: str | None,
    session_id: str,
    sequence: int,
    interrupted: bool,
) -> dict[str, Any]:
    return {
        "reply": "请求已打断。" if interrupted else "请求未完成，请稍后重试。",
        "traceId": trace_id,
        "sessionId": session_id,
        "runId": run_id,
        "provider": "unknown",
        "toolCalls": [],
        "interrupted": interrupted,
        "seq": sequence,
        "eventId": f"{trace_id}:{sequence}",
    }


def _error_payload(*, trace_id: str, run_id: str | None, sequence: int) -> dict[str, Any]:
    return {
        "traceId": trace_id,
        "runId": run_id,
        "message": "流式连接暂时不可用，请稍后重试。",
        "seq": sequence,
        "eventId": f"{trace_id}:{sequence}",
    }


def _safe_sse_value(value: Any) -> str | None:
    if value is None:
        return None
    clean = str(value).replace("\r", "").replace("\n", "").strip()
    return clean[:128] or None


async def _client_disconnected(request: Request) -> bool:
    try:
        return await request.is_disconnected()
    except (RuntimeError, OSError):
        # Some ASGI test transports do not expose disconnect state.
        return False
