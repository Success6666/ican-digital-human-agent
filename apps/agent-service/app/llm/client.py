"""Small provider-neutral LLM client used only when explicitly configured."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field

from ..agent.models import ExpressionName, PerformanceCue


class LlmGeneration(BaseModel):
    """Structured model output consumed by the Agent and presentation layers."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    reply: str = Field(min_length=1, max_length=20_000)
    presentation: PerformanceCue = Field(default_factory=lambda: PerformanceCue(expression=ExpressionName.SPEAKING, lipSync=True))


class LlmClient(Protocol):
    enabled: bool

    async def complete(self, *, message: str, context: list[str] | None = None) -> str | LlmGeneration: ...

    async def stream(self, *, message: str, context: list[str] | None = None) -> AsyncIterator[str]: ...


class OpenAICompatibleLlm:
    def __init__(self, *, enabled: bool, base_url: str, api_key: str, model: str, temperature: float = 0.2, max_tokens: int = 1024, timeout_seconds: float = 20.0) -> None:
        self.enabled = enabled
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout_seconds = timeout_seconds

    def reconfigure(self, *, enabled: bool, base_url: str, api_key: str, model: str, temperature: float, max_tokens: int) -> None:
        self.enabled = enabled
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    async def complete(self, *, message: str, context: list[str] | None = None) -> LlmGeneration:
        if not self.enabled or not self.base_url or not self.api_key or not self.model:
            raise RuntimeError("llm is not configured")
        prompt = message
        if context:
            prompt = f"参考资料：\n{chr(10).join(context[:3])}\n\n用户问题：{message}"
        pieces: list[str] = []
        async for piece in self.stream(message=prompt):
            pieces.append(piece)
        content = "".join(pieces).strip()
        if not content:
            raise RuntimeError("llm service returned no text")
        return parse_generation(content)

    async def stream(self, *, message: str, context: list[str] | None = None) -> AsyncIterator[str]:
        if not self.enabled or not self.base_url or not self.api_key or not self.model:
            raise RuntimeError("llm is not configured")
        prompt = message
        if context:
            prompt = f"参考资料：\n{chr(10).join(context[:3])}\n\n用户问题：{message}"
        payload = {
                "model": self.model,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "stream": True,
                "messages": [{"role": "system", "content": _structured_system_prompt()}, {"role": "user", "content": prompt}],
        }
        timeout = httpx.Timeout(connect=8.0, read=max(45.0, self.timeout_seconds), write=15.0, pool=8.0)
        last_error: Exception | None = None
        delivered = ""
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=timeout, trust_env=True) as client:
                    async with client.stream(
                        "POST",
                        self._completion_url(),
                        json=payload,
                        headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json", "Accept": "text/event-stream"},
                    ) as response:
                        if response.status_code >= 400:
                            detail = (await response.aread()).decode("utf-8", errors="replace")[:500]
                            raise RuntimeError(f"llm upstream HTTP {response.status_code}: {detail}")
                        attempt_text = ""
                        async for line in response.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            data = line[5:].strip()
                            if data == "[DONE]":
                                return
                            try:
                                chunk: Any = json.loads(data)
                            except json.JSONDecodeError:
                                continue
                            choices = chunk.get("choices") if isinstance(chunk, dict) else None
                            choice = choices[0] if isinstance(choices, list) and choices else {}
                            delta = choice.get("delta", {}) if isinstance(choice, dict) else {}
                            text = delta.get("content") if isinstance(delta, dict) else None
                            if isinstance(text, str) and text:
                                attempt_text += text
                                if delivered.startswith(attempt_text):
                                    continue
                                if attempt_text.startswith(delivered):
                                    new_text = attempt_text[len(delivered):]
                                    delivered = attempt_text
                                    if new_text:
                                        yield new_text
                                    continue
                                raise RuntimeError("llm retry stream diverged from the delivered prefix")
                        return
            except (httpx.HTTPError, OSError, RuntimeError) as exc:
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(0.35 * (2 ** attempt))
        raise RuntimeError(f"llm request failed after retries: {last_error}") from last_error

    def _completion_url(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/chat/completions"


def _structured_system_prompt() -> str:
    return (
        "你是数字人 Agent。只输出 JSON，不要 Markdown。字段为 reply 和 presentation。"
        "presentation 必须包含 expression、intensity、durationMs、gaze、gesture、action、lipSync、interruptible。"
        "expression 只能是 listening、thinking、speaking、acknowledging、relieved、interrupted、neutral；"
        "intensity 为 0 到 1，durationMs 为 0 到 120000，gaze 只能是 camera、user、away、none。"
        "gesture 和 action 使用简短英文语义名，不支持的动作填 null。"
    )


def parse_generation(content: str) -> LlmGeneration:
    try:
        raw = json.loads(content.strip().removeprefix("```json").removesuffix("```").strip())
        return LlmGeneration.model_validate(raw)
    except Exception:
        # Provider models that ignore response_format remain usable; the
        # presentation layer supplies a safe speaking cue.
        return LlmGeneration(reply=content.strip())


def extract_reply_prefix(content: str) -> tuple[str, bool]:
    """Decode the reply field while a structured JSON response is arriving."""

    marker = '"reply"'
    key = content.find(marker)
    if key < 0:
        stripped = content.lstrip()
        if not stripped or stripped.startswith(("{", "```")):
            return "", False
        return content, False
    start = content.find('"', key + len(marker))
    if start < 0:
        return "", False
    start += 1
    decoded: list[str] = []
    escaped = False
    index = start
    while index < len(content):
        char = content[index]
        if escaped:
            decoded.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
            decoded.append(char)
        elif char == '"':
            try:
                return json.loads('"' + "".join(decoded) + '"'), True
            except json.JSONDecodeError:
                return "".join(decoded), False
        else:
            decoded.append(char)
        index += 1
    encoded = "".join(decoded)
    if escaped and encoded.endswith("\\"):
        encoded = encoded[:-1]
    try:
        return json.loads('"' + encoded + '"'), False
    except json.JSONDecodeError:
        return encoded, False
