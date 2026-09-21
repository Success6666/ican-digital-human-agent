"""Pi-style agent loop primitives adapted for the Python runtime.

The engine owns event ordering, bounded tool execution, steering/follow-up
queues and approval hooks.  Provider and MCP details stay behind callables.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

from ..domain.models import ToolCallRecord
from .models import ToolSpec


@dataclass(frozen=True, slots=True)
class ToolInvocation:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    call_id: str = field(default_factory=lambda: f"tool-{uuid4().hex}")


@dataclass(frozen=True, slots=True)
class LoopEvent:
    type: Literal[
        "tool_execution_start",
        "tool_execution_end",
        "tool_approval_required",
        "steering_queued",
        "follow_up_queued",
    ]
    run_id: str
    tool_call_id: str | None = None
    tool_name: str | None = None
    arguments: dict[str, Any] | None = None
    result: ToolCallRecord | None = None
    is_error: bool = False
    approval_id: str | None = None


class ApprovalStore:
    """Bounded in-memory HITL gate; unresolved approvals expire automatically."""

    def __init__(self, *, max_pending: int = 4096, timeout_seconds: float = 120.0) -> None:
        self.max_pending = max_pending
        self.timeout_seconds = timeout_seconds
        self._pending: dict[str, tuple[asyncio.Future[bool], str | None]] = {}

    def begin(self, approval_id: str, *, scope_id: str | None = None) -> bool:
        if approval_id in self._pending or len(self._pending) >= self.max_pending:
            return False
        loop = asyncio.get_running_loop()
        self._pending[approval_id] = (loop.create_future(), scope_id)
        return True

    async def wait(self, approval_id: str, *, scope_id: str | None = None) -> bool:
        pending = self._pending.get(approval_id)
        if pending is None:
            if not self.begin(approval_id, scope_id=scope_id):
                return False
            pending = self._pending[approval_id]
        future, pending_scope = pending
        if pending_scope != scope_id:
            return False
        try:
            return await asyncio.wait_for(future, timeout=self.timeout_seconds)
        except TimeoutError:
            return False
        finally:
            self._pending.pop(approval_id, None)

    def resolve(self, approval_id: str, approved: bool, *, scope_id: str | None = None) -> bool:
        pending = self._pending.get(approval_id)
        if pending is None:
            return False
        future, pending_scope = pending
        if pending_scope != scope_id or future.done():
            return False
        future.set_result(bool(approved))
        return True

    def cancel(self, approval_id: str, *, scope_id: str | None = None) -> bool:
        pending = self._pending.get(approval_id)
        if pending is None:
            return False
        future, pending_scope = pending
        if pending_scope != scope_id or future.done():
            return False
        future.cancel()
        return True

    def reject_scope(self, scope_id: str) -> int:
        rejected = 0
        for future, pending_scope in list(self._pending.values()):
            if pending_scope == scope_id and not future.done():
                future.set_result(False)
                rejected += 1
        return rejected


class MessageQueue:
    """Small bounded queue matching Pi's steering/follow-up semantics."""

    def __init__(self, *, max_items: int = 64) -> None:
        self.max_items = max_items
        self._steering: list[str] = []
        self._follow_up: list[str] = []

    def put_steering(self, message: str) -> bool:
        return self._put(self._steering, message, self.max_items)

    def put_follow_up(self, message: str) -> bool:
        return self._put(self._follow_up, message, self.max_items)

    def drain_steering(self, *, all_items: bool = False) -> list[str]:
        return self._drain(self._steering, all_items=all_items)

    def drain_follow_up(self) -> list[str]:
        return self._drain(self._follow_up, all_items=True)

    def clear(self) -> dict[str, list[str]]:
        result = {"steering": list(self._steering), "followUp": list(self._follow_up)}
        self._steering.clear()
        self._follow_up.clear()
        return result

    @staticmethod
    def _put(target: list[str], message: str, max_items: int = 64) -> bool:
        value = message.strip()
        if not value or len(target) >= max_items:
            return False
        target.append(value)
        return True

    @staticmethod
    def _drain(target: list[str], *, all_items: bool) -> list[str]:
        if all_items:
            result, target[:] = list(target), []
            return result
        return [target.pop(0)] if target else []


EventSink = Callable[[LoopEvent], Awaitable[None] | None]
ToolExecutor = Callable[[ToolInvocation], Awaitable[ToolCallRecord]]


class AgentLoopEngine:
    """Execute a bounded tool batch with deterministic Pi-style lifecycle events."""

    def __init__(self, *, max_parallel: int = 4, approval_store: ApprovalStore | None = None) -> None:
        self.max_parallel = max(1, max_parallel)
        self.approvals = approval_store or ApprovalStore()

    async def execute_tools(
        self,
        *,
        run_id: str,
        invocations: Iterable[ToolInvocation],
        execute: ToolExecutor,
        specs: dict[str, ToolSpec] | None = None,
        emit: EventSink | None = None,
        signal: asyncio.Event | None = None,
        scope_id: str | None = None,
        sequential: bool = False,
    ) -> list[ToolCallRecord]:
        items = list(invocations)
        if sequential:
            results: list[ToolCallRecord] = []
            for item in items:
                results.append(await self._execute_one(run_id, item, execute, specs, emit, signal, scope_id))
            return results
        semaphore = asyncio.Semaphore(self.max_parallel)

        async def worker(item: ToolInvocation) -> ToolCallRecord:
            async with semaphore:
                return await self._execute_one(run_id, item, execute, specs, emit, signal, scope_id)

        return list(await asyncio.gather(*(worker(item) for item in items)))

    async def _execute_one(
        self,
        run_id: str,
        invocation: ToolInvocation,
        execute: ToolExecutor,
        specs: dict[str, ToolSpec] | None,
        emit: EventSink | None,
        signal: asyncio.Event | None,
        scope_id: str | None,
    ) -> ToolCallRecord:
        await self._emit(emit, LoopEvent("tool_execution_start", run_id, invocation.call_id, invocation.name, invocation.arguments))
        if signal is not None and signal.is_set():
            return ToolCallRecord(name=invocation.name, arguments=invocation.arguments, error="run interrupted")
        spec = (specs or {}).get(invocation.name)
        if spec and spec.requires_confirmation:
            approval_id = f"approval-{uuid4().hex}"
            if not self.approvals.begin(approval_id, scope_id=scope_id):
                result = ToolCallRecord(name=invocation.name, arguments=invocation.arguments, error="approval capacity reached")
                await self._emit(emit, LoopEvent("tool_execution_end", run_id, invocation.call_id, invocation.name, invocation.arguments, result=result, is_error=True, approval_id=approval_id))
                return result
            await self._emit(emit, LoopEvent("tool_approval_required", run_id, invocation.call_id, invocation.name, invocation.arguments, approval_id=approval_id))
            approved = await self.approvals.wait(approval_id, scope_id=scope_id)
            if not approved:
                result = ToolCallRecord(name=invocation.name, arguments=invocation.arguments, error="tool execution requires approval")
                await self._emit(emit, LoopEvent("tool_execution_end", run_id, invocation.call_id, invocation.name, invocation.arguments, result=result, is_error=True, approval_id=approval_id))
                return result
        try:
            result = await execute(invocation)
        except Exception as exc:  # defensive tool boundary
            result = ToolCallRecord(name=invocation.name, arguments=invocation.arguments, error=str(exc)[:300])
        await self._emit(emit, LoopEvent("tool_execution_end", run_id, invocation.call_id, invocation.name, invocation.arguments, result=result, is_error=bool(result.error)))
        return result

    @staticmethod
    async def _emit(emit: EventSink | None, event: LoopEvent) -> None:
        if emit is None:
            return
        value = emit(event)
        if asyncio.iscoroutine(value):
            await value


__all__ = ["AgentLoopEngine", "ApprovalStore", "LoopEvent", "MessageQueue", "ToolInvocation"]
