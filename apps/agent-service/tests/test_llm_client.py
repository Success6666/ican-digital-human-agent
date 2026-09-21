from __future__ import annotations

import json

import httpx
import pytest

from app.agent.mofa_capabilities import (
    MOFA_ACTION_INTENT_OPTIONS,
    MOFA_ACTION_INTENTS,
    MOFA_EMOTIONS,
    normalize_mofa_action_intent,
    normalize_mofa_emotion,
)
from app.llm.client import (
    OpenAICompatibleLlm,
    _structured_system_prompt,
    extract_reply_prefix,
    parse_generation,
)


def test_completion_url_accepts_base_or_full_endpoint() -> None:
    base = OpenAICompatibleLlm(enabled=True, base_url="https://example.test/v1/", api_key="k", model="m")
    full = OpenAICompatibleLlm(enabled=True, base_url="https://example.test/v1/chat/completions", api_key="k", model="m")
    assert base._completion_url().endswith("/v1/chat/completions")
    assert full._completion_url().endswith("/v1/chat/completions")


def test_extract_reply_prefix_handles_partial_json() -> None:
    assert extract_reply_prefix('{"reply":"你好') == ("你好", False)
    assert extract_reply_prefix('{"reply":"你好","presentation":{}}') == ("你好", True)


def test_parse_generation_keeps_reply_when_presentation_has_provider_specific_types() -> None:
    generated = parse_generation(
        '{"reply":"我是你的数字人助手。","presentation":'
        '{"expression":"speaking","intensity":0.6,"durationMs":3000,'
        '"gaze":"camera","gesture":"wave_hand","action":"Hello",'
        '"lipSync":"speaking","interruptible":true}}'
    )
    assert generated.reply == "我是你的数字人助手。"
    assert generated.presentation.lip_sync is True
    assert generated.presentation.expression.value == "neutral"
    assert generated.presentation.gesture is None
    assert generated.presentation.action == "Hello"


def test_structured_prompt_and_normalizers_cover_only_official_mofa_catalogs() -> None:
    prompt = _structured_system_prompt()
    assert len(MOFA_ACTION_INTENTS) == 70
    assert MOFA_EMOTIONS == ("happy", "sad", "angry", "surprised", "neutral")
    for emotion in MOFA_EMOTIONS:
        assert emotion in prompt
        assert normalize_mofa_emotion(emotion.upper()) == emotion
    for action in MOFA_ACTION_INTENTS:
        assert action in prompt
        assert normalize_mofa_action_intent(action.lower()) == action
    for action, label in MOFA_ACTION_INTENT_OPTIONS:
        assert f"{label}={action}" in prompt
    assert normalize_mofa_emotion("serious") is None
    assert normalize_mofa_emotion("excited") is None
    assert normalize_mofa_action_intent("greet") is None
    assert normalize_mofa_action_intent("RightSide02") is None


def test_parse_generation_supports_fenced_and_prefixed_json() -> None:
    generated = parse_generation('模型输出如下：\n```json\n{"reply":"已完成"}\n```')
    assert generated.reply == "已完成"


def test_parse_generation_does_not_expose_json_when_tail_is_truncated() -> None:
    generated = parse_generation('{"reply":"先给你结果","presentation":{')
    assert generated.reply == "先给你结果"


def test_deepseek_payload_disables_thinking_without_json_grammar() -> None:
    llm = OpenAICompatibleLlm(enabled=True, base_url="https://api.deepseek.com/v1", api_key="k", model="deepseek-v4-flash")
    payload = llm._payload("你好")
    assert payload["thinking"] == {"type": "disabled"}
    assert "response_format" not in payload


@pytest.mark.asyncio
async def test_stream_reads_sse_deltas(monkeypatch: pytest.MonkeyPatch) -> None:
    llm = OpenAICompatibleLlm(enabled=True, base_url="https://example.test/v1", api_key="k", model="m")

    class FakeResponse:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def aiter_lines(self):
            for content in ('{"reply":"你', '好"}'):
                yield "data: " + json.dumps({"choices": [{"delta": {"content": content}}]})
            yield "data: " + json.dumps({"choices": [], "usage": {"total_tokens": 12}})
            yield "data: [DONE]"

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def stream(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    assert [item async for item in llm.stream(message="你好")] == ['{"reply":"你', '好"}']
