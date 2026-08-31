"""Small provider-neutral LLM client used only when explicitly configured."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Protocol
from urllib.request import Request, urlopen
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
        return await asyncio.to_thread(self._complete_sync, prompt)

    def _complete_sync(self, prompt: str) -> str:
        request = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps({
                "model": self.model,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": _structured_system_prompt()}, {"role": "user", "content": prompt}],
            }).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310 - operator-provided endpoint.
            payload: Any = json.loads(response.read().decode("utf-8"))
        content = payload.get("choices", [{}])[0].get("message", {}).get("content") if isinstance(payload, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("llm service returned no text")
        return _parse_generation(content)


def _structured_system_prompt() -> str:
    return (
        "你是数字人 Agent。只输出 JSON，不要 Markdown。字段为 reply 和 presentation。"
        "presentation 必须包含 expression、intensity、durationMs、gaze、gesture、action、lipSync、interruptible。"
        "expression 只能是 listening、thinking、speaking、acknowledging、relieved、interrupted、neutral；"
        "intensity 为 0 到 1，durationMs 为 0 到 120000，gaze 只能是 camera、user、away、none。"
        "gesture 和 action 使用简短英文语义名，不支持的动作填 null。"
    )


def _parse_generation(content: str) -> LlmGeneration:
    try:
        raw = json.loads(content.strip().removeprefix("```json").removesuffix("```").strip())
        return LlmGeneration.model_validate(raw)
    except Exception:
        # Provider models that ignore response_format remain usable; the
        # presentation layer supplies a safe speaking cue.
        return LlmGeneration(reply=content.strip())
