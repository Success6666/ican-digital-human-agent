from __future__ import annotations

import json

import httpx
import pytest

from app.llm.client import OpenAICompatibleLlm, extract_reply_prefix


def test_completion_url_accepts_base_or_full_endpoint() -> None:
    base = OpenAICompatibleLlm(enabled=True, base_url="https://example.test/v1/", api_key="k", model="m")
    full = OpenAICompatibleLlm(enabled=True, base_url="https://example.test/v1/chat/completions", api_key="k", model="m")
    assert base._completion_url().endswith("/v1/chat/completions")
    assert full._completion_url().endswith("/v1/chat/completions")


def test_extract_reply_prefix_handles_partial_json() -> None:
    assert extract_reply_prefix('{"reply":"你好') == ("你好", False)
    assert extract_reply_prefix('{"reply":"你好","presentation":{}}') == ("你好", True)


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
