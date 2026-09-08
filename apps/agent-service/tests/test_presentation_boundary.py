from __future__ import annotations

import pytest
import asyncio
import time

from app.avatar.presentation import PresentationLayer, ProviderRuntime
from app.agent.models import PerformanceCue
from app.agent.response import build_agent_response
from app.domain.models import AgentResponse, AvatarCapabilities, ChatResult, ProviderResult


class RecordingRuntime:
    name = "recording"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def send_text(self, session_id: str, text: str, *, mode: str = "text") -> ProviderResult:
        self.calls.append((session_id, text, mode))
        return ProviderResult(provider=self.name, metadata={"runtime": "recording"})


class RecordingPublisher:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def publish(self, *, topic: str, payload: dict) -> str:
        self.calls.append({"topic": topic, "payload": payload})
        return "message-1"


class SlowPublisher(RecordingPublisher):
    async def publish(self, *, topic: str, payload: dict) -> str:
        await asyncio.sleep(0.05)
        return await super().publish(topic=topic, payload=payload)


@pytest.mark.asyncio
async def test_presentation_layer_keeps_agent_response_out_of_provider_contract() -> None:
    runtime = RecordingRuntime()
    response = AgentResponse(
        text="已完成",
        emotion="speaking",
        gesture="small_nod",
        performance={"expression": "speaking", "lipSync": True},
        traceId="trace-1",
        sessionId="session-1",
        runId="run-1",
    )

    result = await PresentationLayer().present(runtime, response)

    assert runtime.calls == [("session-1", "已完成", "agent_response")]
    assert result.metadata["agentResponse"]["text"] == "已完成"
    assert result.metadata["agentResponse"]["emotion"] == "speaking"
    assert result.metadata["agentResponse"]["runId"] == "run-1"
    assert result.metadata["performance"]["lipSync"] is True

    runtime_result = await ProviderRuntime(runtime).present(response)
    assert runtime_result.metadata["agentResponse"]["sessionId"] == "session-1"


@pytest.mark.asyncio
async def test_presentation_does_not_wait_for_message_bus_before_provider() -> None:
    publisher = RecordingPublisher()
    runtime = RecordingRuntime()
    response = AgentResponse(text="快速响应", traceId="trace-2", sessionId="session-2")

    result = await PresentationLayer(publisher).present(runtime, response)
    await __import__("asyncio").sleep(0)

    assert result.provider == "recording"
    assert runtime.calls == [("session-2", "快速响应", "agent_response")]
    assert publisher.calls[0]["topic"] == "presentation"


@pytest.mark.asyncio
async def test_presentation_overlaps_slow_message_bus_with_provider_call() -> None:
    publisher = SlowPublisher()
    runtime = RecordingRuntime()
    response = AgentResponse(text="并行发送", traceId="trace-3", sessionId="session-3")

    started = time.perf_counter()
    await PresentationLayer(publisher).present(runtime, response)
    elapsed_ms = (time.perf_counter() - started) * 1000
    await asyncio.sleep(0.06)

    assert elapsed_ms < 30
    assert publisher.calls


def test_agent_response_contract_is_vendor_neutral() -> None:
    response = AgentResponse(text="hello", traceId="t", sessionId="s")
    assert response.emotion == "neutral"
    assert response.gesture is None
    assert response.run_id is None
    assert AvatarCapabilities(external_runtime=True).external_runtime is True
    assert AvatarCapabilities().interrupt_scope == "local"


def test_agent_response_exposes_only_official_mofa_emotions() -> None:
    official = build_agent_response(
        text="完成",
        trace_id="trace-official",
        session_id="session-official",
        presentation=PerformanceCue(expression="surprised"),
    )
    internal = build_agent_response(
        text="处理中",
        trace_id="trace-internal",
        session_id="session-internal",
        presentation=PerformanceCue(expression="speaking"),
    )
    assert official.emotion == "surprised"
    assert internal.emotion == "neutral"


def test_chat_result_populates_alias_fields_from_domain_names() -> None:
    result = ChatResult(
        reply="已完成",
        trace_id="trace-1",
        session_id="session-1",
        run_id="run-1",
        provider="mock",
        agent_response=AgentResponse(text="已完成", runId="run-1"),
    )

    assert result.run_id == "run-1"
    assert result.agent_response is not None
    assert result.agent_response.run_id == "run-1"
