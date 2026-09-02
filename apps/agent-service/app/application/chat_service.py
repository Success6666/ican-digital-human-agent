"""Chat use cases wrapping validation, ownership and graph execution."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import time
from typing import Any
import uuid
import hashlib
import json

from ..evaluation.service import EvaluationService
from ..domain.models import ChatResult
from ..graph.runtime import AgentGraphRuntime
from .chat_evaluation import ChatEvaluationRecorder
from .chat_evaluation import number as _number_value
from .chat_evaluation import result_status as _result_status_value
from .errors import InvalidMessageError
from .session_service import SessionApplicationService
from ..infrastructure.profile_store import AccountPreferenceStore
from ..infrastructure.response_cache import ResponseCache

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
        profile_store: AccountPreferenceStore | None = None,
        response_cache: ResponseCache | None = None,
        cache_model: str = "default",
    ) -> None:
        self.graph = graph
        self.sessions = sessions
        self.max_message_length = max_message_length
        self.evaluation = evaluation
        self._evaluation_recorder = ChatEvaluationRecorder(evaluation)
        self.profile_store = profile_store
        self.response_cache = response_cache
        self.cache_model = cache_model

    async def send(
        self, *, user_id: str, user_name: str, session_id: str, message: str,
        history: list[dict[str, str]] | None = None, tenant_id: str = "default",
    ) -> ChatResult:
        clean = self._validate(message)
        preferences_task = asyncio.create_task(self._preferences(tenant_id=tenant_id, user_id=user_id))
        try:
            await self.sessions.get_for_user(user_id=user_id, session_id=session_id)
            run_id = await self.sessions.begin_run(user_id=user_id, session_id=session_id)
        except BaseException:
            preferences_task.cancel()
            await asyncio.gather(preferences_task, return_exceptions=True)
            raise
        started = time.perf_counter()
        preferences = await preferences_task
        request_context = self._request_context(preferences, history)
        cache_key = self._cache_key(tenant_id, user_id, clean, preferences, history)
        try:
            async def compute() -> ChatResult:
                return await self.graph.invoke(
                    user_id=user_id,
                    user_name=user_name,
                    session_id=session_id,
                    message=clean,
                    run_id=run_id,
                    profile_context=request_context,
                )
            if self.response_cache is not None and cache_key:
                result, cache_hit = await self.response_cache.get_or_compute(cache_key, compute)
                if cache_hit:
                    result = result.model_copy(update={"session_id": session_id, "run_id": run_id, "trace_id": uuid.uuid4().hex, "cache_hit": True})
            else:
                result = await compute()
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
        self,
        *,
        user_id: str,
        user_name: str,
        session_id: str,
        message: str,
        run_id: str | None = None,
        history: list[dict[str, str]] | None = None,
        tenant_id: str = "default",
    ) -> AsyncIterator[dict[str, Any]]:
        clean = self._validate(message)
        preferences_task = asyncio.create_task(self._preferences(tenant_id=tenant_id, user_id=user_id))
        try:
            record = await self.sessions.get_for_user(user_id=user_id, session_id=session_id)
            if run_id is None:
                run_id = await self.sessions.begin_run(user_id=user_id, session_id=session_id)
            elif record.active_run_id != run_id:
                # A realtime connection can reserve a run before handing the
                # stream to this service. Reject a stale reservation instead of
                # silently superseding it with a second generation.
                raise InvalidMessageError("run is not active")
            if not run_id:
                raise InvalidMessageError("session is not available")
            preferences = await preferences_task
        except BaseException:
            preferences_task.cancel()
            await asyncio.gather(preferences_task, return_exceptions=True)
            raise
        request_context = self._request_context(preferences, history)
        cache_key = self._cache_key(tenant_id, user_id, clean, preferences, history)
        if self.response_cache is not None and cache_key:
            cached = await self.response_cache.get(cache_key)
            if cached is not None:
                return self._cached_stream_events(cached, session_id=session_id, run_id=run_id)
        return self._stream_events(
            user_id=user_id,
            user_name=user_name,
            session_id=session_id,
            message=clean,
            run_id=run_id,
            profile_context=request_context,
            cache_key=cache_key,
        )

    async def _stream_events(
        self, *, user_id: str, user_name: str, session_id: str, message: str, run_id: str,
        profile_context: str = "", cache_key: str | None = None,
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
            profile_context=profile_context,
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
            if self.response_cache is not None and cache_key and status == "success" and not tools:
                cached = ChatResult(
                    reply=str(done_data.get("reply") or "".join(deltas)),
                    trace_id=trace_id or uuid.uuid4().hex,
                    session_id=session_id,
                    run_id=run_id,
                    provider=str(done_data.get("provider") or "unknown"),
                    interrupted=False,
                    cache_hit=True,
                )
                await self.response_cache.set(cache_key, cached)
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

    async def _preferences(self, *, tenant_id: str, user_id: str) -> dict[str, str]:
        if self.profile_store is None:
            return {}
        return await self.profile_store.get(tenant_id=tenant_id, user_id=user_id)

    def _cache_key(
        self, tenant_id: str, user_id: str, message: str, preferences: dict[str, str],
        history: list[dict[str, str]] | None = None,
    ) -> str | None:
        if self.response_cache is None:
            return None
        profile_version = hashlib.sha256(
            json.dumps(
                {"preferences": preferences, "history": history or []},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:16]
        return self.response_cache.key(
            tenant_id=tenant_id,
            user_id=user_id,
            message=message,
            model=self.cache_model,
            profile_version=profile_version,
        )

    @staticmethod
    def _profile_context(preferences: dict[str, str]) -> str:
        return "; ".join(f"{key}={value}" for key, value in sorted(preferences.items()))[:1200]

    @classmethod
    def _request_context(
        cls, preferences: dict[str, str], history: list[dict[str, str]] | None,
    ) -> str:
        sections: list[str] = []
        profile = cls._profile_context(preferences)
        if profile:
            sections.append(f"用户沟通偏好：{profile}")
        turns: list[str] = []
        for item in (history or [])[-12:]:
            role = "用户" if item.get("role") == "user" else "助手"
            content = str(item.get("content") or "").strip().replace("\n", " ")[:600]
            if content:
                turns.append(f"{role}：{content}")
        if turns:
            sections.append("最近对话（仅作为本轮上下文）：\n" + "\n".join(turns))
        return "\n".join(sections)[:4000]

    async def _cached_stream_events(self, result: ChatResult, *, session_id: str, run_id: str) -> AsyncIterator[dict[str, Any]]:
        trace_id = uuid.uuid4().hex
        yield {"event": "start", "data": {"traceId": trace_id, "sessionId": session_id, "runId": run_id, "cacheHit": True}}
        if result.reply:
            yield {"event": "delta", "data": {"traceId": trace_id, "runId": run_id, "text": result.reply, "cacheHit": True}}
        yield {"event": "done", "data": {"traceId": trace_id, "sessionId": session_id, "runId": run_id, "reply": result.reply, "provider": result.provider, "cacheHit": True}}

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
