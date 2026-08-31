"""Small provider-neutral LLM client used only when explicitly configured."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Protocol
from urllib.request import Request, urlopen


class LlmClient(Protocol):
    enabled: bool

    async def complete(self, *, message: str, context: list[str] | None = None) -> str: ...


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

    async def complete(self, *, message: str, context: list[str] | None = None) -> str:
        if not self.enabled or not self.base_url or not self.api_key or not self.model:
            raise RuntimeError("llm is not configured")
        prompt = message
        if context:
            prompt = f"参考资料：\n{chr(10).join(context[:3])}\n\n用户问题：{message}"
        return await asyncio.to_thread(self._complete_sync, prompt)

    def _complete_sync(self, prompt: str) -> str:
        request = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps({"model": self.model, "temperature": self.temperature, "max_tokens": self.max_tokens, "messages": [{"role": "user", "content": prompt}]}).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310 - operator-provided endpoint.
            payload: Any = json.loads(response.read().decode("utf-8"))
        content = payload.get("choices", [{}])[0].get("message", {}).get("content") if isinstance(payload, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("llm service returned no text")
        return content.strip()
