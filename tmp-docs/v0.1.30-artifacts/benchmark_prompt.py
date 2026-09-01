from __future__ import annotations

import asyncio
import json
import sys
import time

import httpx


SYSTEM = (
    "你是数字人 Agent。只输出 JSON，不要 Markdown。字段为 reply 和 presentation。"
    "presentation 必须包含 expression、intensity、durationMs、gaze、gesture、action、lipSync、interruptible。"
    "expression 只能是 listening、thinking、speaking、acknowledging、relieved、interrupted、neutral；"
    "intensity 为 0 到 1，durationMs 为 0 到 120000，gaze 只能是 camera、user、away、none。"
    "gesture 和 action 使用简短英文语义名，不支持的动作填 null；lipSync 和 interruptible 必须是 JSON 布尔值。"
    "先输出 reply，回答直接、自然、简洁。"
)


async def main() -> None:
    with open(sys.argv[1], encoding="utf-8") as source:
        llm = json.load(source)["llm"]
    async with httpx.AsyncClient(timeout=60, trust_env=True) as client:
        for max_tokens in (128, 256, 512, 1024):
            payload = {
                "model": llm["model"],
                "temperature": llm["temperature"],
                "max_tokens": max_tokens,
                "stream": True,
                "response_format": {"type": "json_object"},
                "thinking": {"type": "disabled"},
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": "请用一句话解释什么是RAG"},
                ],
            }
            started = time.perf_counter()
            first = None
            content = ""
            async with client.stream(
                "POST",
                llm["base_url"].rstrip("/") + "/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {llm['api_key']}"},
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    delta = json.loads(data).get("choices", [{}])[0].get("delta", {})
                    text = delta.get("content")
                    if text:
                        first = first or (time.perf_counter() - started) * 1000
                        content += text
            total = (time.perf_counter() - started) * 1000
            print(json.dumps({"max_tokens": max_tokens, "first_ms": round(first or -1, 2), "total_ms": round(total, 2), "chars": len(content)}, ensure_ascii=False))


asyncio.run(main())
