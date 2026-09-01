"""Small provider-neutral LLM client used only when explicitly configured."""

from __future__ import annotations

import asyncio
import json
import math
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
        self._client: httpx.AsyncClient | None = None
        self._structured_options_supported = True

    def reconfigure(self, *, enabled: bool, base_url: str, api_key: str, model: str, temperature: float, max_tokens: int) -> None:
        self.enabled = enabled
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._structured_options_supported = True

    async def aclose(self) -> None:
        """Release the shared keep-alive client during application shutdown."""

        if self._client is not None:
            await self._client.aclose()
            self._client = None

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
        payload = self._payload(prompt)
        timeout = httpx.Timeout(connect=8.0, read=max(45.0, self.timeout_seconds), write=15.0, pool=8.0)
        last_error: Exception | None = None
        delivered = ""
        payloads = [payload]
        if self._structured_options_supported and any(key in payload for key in ("thinking", "response_format")):
            # Some OpenAI-compatible gateways reject one or both optional
            # fields.  The second payload keeps the generic client usable.
            fallback = dict(payload)
            fallback.pop("thinking", None)
            fallback.pop("response_format", None)
            payloads.append(fallback)
        fallback_requested = False
        for payload_index, request_payload in enumerate(payloads):
            for attempt in range(3):
                try:
                    client = self._get_client(timeout)
                    async with client.stream(
                        "POST",
                        self._completion_url(),
                        json=request_payload,
                        headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json", "Accept": "text/event-stream"},
                    ) as response:
                        if response.status_code >= 400:
                            detail = (await response.aread()).decode("utf-8", errors="replace")[:500]
                            if payload_index == 0 and _is_optional_parameter_error(detail):
                                self._structured_options_supported = False
                                fallback_requested = True
                                break
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
            if fallback_requested and payload_index == 0 and len(payloads) > 1:
                continue
            break
        raise RuntimeError(f"llm request failed after retries: {last_error}") from last_error

    def _get_client(self, timeout: httpx.Timeout) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=timeout, trust_env=True)
        return self._client

    def _payload(self, prompt: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": True,
            "messages": [{"role": "system", "content": _structured_system_prompt()}, {"role": "user", "content": prompt}],
        }
        if self._structured_options_supported:
            payload["response_format"] = {"type": "json_object"}
            if self._is_deepseek():
                payload["thinking"] = {"type": "disabled"}
        return payload

    def _is_deepseek(self) -> bool:
        value = f"{self.base_url} {self.model}".casefold()
        return "deepseek" in value

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
        "gesture 和 action 使用简短英文语义名，不支持的动作填 null；lipSync 和 interruptible 必须是 JSON 布尔值。"
        "先输出 reply，回答直接、自然、简洁。"
    )


def parse_generation(content: str) -> LlmGeneration:
    text = content.strip()
    raw = _decode_json_payload(text)
    if isinstance(raw, dict):
        reply = _coerce_reply(raw.get("reply"))
        if reply:
            return LlmGeneration(reply=reply, presentation=_normalize_presentation(raw.get("presentation")))
        return LlmGeneration(reply="模型响应格式异常，请重试。")
    # A provider may truncate the tail after emitting a complete reply field.
    prefix, _ = extract_reply_prefix(text)
    if prefix.strip():
        return LlmGeneration(reply=prefix.strip())
    # Provider models that ignore response_format remain usable; never expose a
    # structured envelope as user-facing text.
    return LlmGeneration(reply="模型响应格式异常，请重试。" if _looks_structured(text) else _plain_text(text))


def _decode_json_payload(content: str) -> Any:
    text = content.strip()
    if text.startswith("```"):
        text = text[3:]
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
        text = text.removesuffix("```").strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        if start < 0:
            return None
        try:
            value, _ = json.JSONDecoder().raw_decode(text[start:])
        except json.JSONDecodeError:
            return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _coerce_reply(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()[:20_000]
    if value is None:
        return ""
    return str(value).strip()[:20_000]


def _normalize_presentation(value: Any) -> PerformanceCue:
    data = value if isinstance(value, dict) else {}
    expression = str(data.get("expression", ExpressionName.SPEAKING)).casefold()
    allowed_expressions = {item.value for item in ExpressionName}
    gaze = str(data.get("gaze", "camera")).casefold()
    allowed_gaze = {"camera", "user", "away", "none"}
    return PerformanceCue(
        expression=expression if expression in allowed_expressions else ExpressionName.SPEAKING,
        intensity=_bounded_float(data.get("intensity", 0.6), default=0.6),
        durationMs=_bounded_int(data.get("durationMs", 3000), default=3000, upper=120_000),
        gaze=gaze if gaze in allowed_gaze else "camera",
        gesture=_optional_text(data.get("gesture")),
        action=_optional_text(data.get("action")),
        lipSync=_coerce_bool(data.get("lipSync", True), default=True),
        interruptible=_coerce_bool(data.get("interruptible", True), default=True),
    )


def _bounded_float(value: Any, *, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, number)) if math.isfinite(number) else default


def _bounded_int(value: Any, *, default: int, upper: int) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(0, min(upper, number))


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:64] or None


def _coerce_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "1", "yes", "on", "speaking", "speech", "enabled"}:
            return True
        if normalized in {"false", "0", "no", "off", "none", "disabled"}:
            return False
    return default


def _plain_text(content: str) -> str:
    text = content.strip()
    if text.startswith("```") and text.endswith("```"):
        text = text[3:-3].strip()
    return text[:20_000] or "已收到请求，我正在处理。"


def _looks_structured(content: str) -> bool:
    text = content.lstrip().casefold()
    return text.startswith(("{", "[", "```json")) or '"reply"' in text or '"presentation"' in text


def _is_optional_parameter_error(detail: str) -> bool:
    lowered = detail.casefold()
    return any(token in lowered for token in ("response_format", "thinking", "unknown parameter", "extra_body"))


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
