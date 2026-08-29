from __future__ import annotations

import pytest

from app.avatar.presentation import PresentationLayer, ProviderRuntime
from app.domain.models import AgentResponse, AvatarCapabilities, ChatResult, ProviderResult


class RecordingRuntime:
    name = "recording"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def send_text(self, session_id: str, text: str, *, mode: str = "text") -> ProviderResult:
        self.calls.append((session_id, text, mode))
        return ProviderResult(provider=self.name, metadata={"runtime": "recording"})


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


def test_agent_response_contract_is_vendor_neutral() -> None:
    response = AgentResponse(text="hello", traceId="t", sessionId="s")
    assert response.emotion == "neutral"
    assert response.gesture is None
    assert response.run_id is None
    assert AvatarCapabilities(external_runtime=True).external_runtime is True


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
