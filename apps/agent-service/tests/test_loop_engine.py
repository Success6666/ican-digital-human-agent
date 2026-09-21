import asyncio

import pytest

from app.agent.loop_engine import (
    AgentLoopEngine,
    LoopEvent,
    MessageQueue,
    ToolInvocation,
)
from app.agent.models import ToolCategory, ToolSpec
from app.domain.models import ToolCallRecord


@pytest.mark.asyncio
async def test_parallel_tool_batch_preserves_input_order_and_emits_lifecycle() -> None:
    engine = AgentLoopEngine(max_parallel=2)
    events: list[LoopEvent] = []

    async def execute(item: ToolInvocation) -> ToolCallRecord:
        await asyncio.sleep(0.01 if item.name == "slow" else 0)
        return ToolCallRecord(name=item.name, arguments=item.arguments, result={"ok": True})

    result = await engine.execute_tools(
        run_id="run-1",
        invocations=[ToolInvocation("slow"), ToolInvocation("fast")],
        execute=execute,
        emit=events.append,
    )

    assert [item.name for item in result] == ["slow", "fast"]
    assert [event.type for event in events] == [
        "tool_execution_start", "tool_execution_start",
        "tool_execution_end", "tool_execution_end",
    ]


@pytest.mark.asyncio
async def test_confirmation_gate_can_be_resolved_without_executing_before_approval() -> None:
    engine = AgentLoopEngine()
    executed = False

    async def execute(item: ToolInvocation) -> ToolCallRecord:
        nonlocal executed
        executed = True
        return ToolCallRecord(name=item.name, result="done")

    async def emit(event: LoopEvent) -> None:
        if event.type == "tool_approval_required":
            assert event.approval_id
            assert engine.approvals.resolve(event.approval_id, True, scope_id="session-b") is False
            assert engine.approvals.resolve(event.approval_id, True, scope_id="session-a")

    result = await engine.execute_tools(
        run_id="run-2",
        invocations=[ToolInvocation("task_runner")],
        specs={"task_runner": ToolSpec(name="task_runner", label="任务", category=ToolCategory.TASK, requires_confirmation=True)},
        execute=execute,
        emit=emit,
        scope_id="session-a",
    )

    assert executed is True
    assert result[0].error is None


@pytest.mark.asyncio
async def test_confirmation_rejection_skips_tool_and_cleans_pending_state() -> None:
    engine = AgentLoopEngine()
    executed = False

    async def execute(item: ToolInvocation) -> ToolCallRecord:
        nonlocal executed
        executed = True
        return ToolCallRecord(name=item.name, result="unexpected")

    async def emit(event: LoopEvent) -> None:
        if event.type == "tool_approval_required":
            assert event.approval_id
            assert engine.approvals.resolve(event.approval_id, False, scope_id="session-a")

    result = await engine.execute_tools(
        run_id="run-rejected",
        invocations=[ToolInvocation("task_runner")],
        specs={"task_runner": ToolSpec(name="task_runner", label="任务", category=ToolCategory.TASK, requires_confirmation=True)},
        execute=execute,
        emit=emit,
        scope_id="session-a",
    )

    assert executed is False
    assert result[0].error == "tool execution requires approval"
    assert engine.approvals.resolve("missing", True, scope_id="session-a") is False


def test_message_queue_supports_one_at_a_time_steering_and_full_follow_up_drain() -> None:
    queue = MessageQueue(max_items=1)
    assert queue.put_steering("先停一下")
    assert not queue.put_steering("第二条")
    assert queue.drain_steering() == ["先停一下"]
    assert queue.put_follow_up("完成后继续")
    assert queue.drain_follow_up() == ["完成后继续"]


@pytest.mark.asyncio
async def test_reject_scope_releases_only_matching_pending_approvals() -> None:
    engine = AgentLoopEngine()
    assert engine.approvals.begin("approval-a", scope_id="session-a")
    assert engine.approvals.begin("approval-b", scope_id="session-b")

    assert engine.approvals.reject_scope("session-a") == 1
    assert await engine.approvals.wait("approval-a", scope_id="session-a") is False
    assert engine.approvals.resolve("approval-b", True, scope_id="session-b")
    assert await engine.approvals.wait("approval-b", scope_id="session-b") is True
