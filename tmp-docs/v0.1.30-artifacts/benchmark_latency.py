from __future__ import annotations

import asyncio
import json
import sys
import time

import httpx


async def main() -> None:
    configuration_path = sys.argv[1] if len(sys.argv) > 1 else "/app/data/runtime-configuration.json"
    with open(configuration_path, encoding="utf-8") as source:
        configuration = json.load(source)["llm"]
    variants = (
        ("thinking_disabled", {"thinking": {"type": "disabled"}, "response_format": {"type": "json_object"}}),
        ("reasoning_none", {"reasoning_effort": "none", "response_format": {"type": "json_object"}}),
        ("json_only", {"response_format": {"type": "json_object"}}),
        ("plain", {}),
    )
    async with httpx.AsyncClient(timeout=60, trust_env=True) as client:
        for name, extras in variants:
            payload = {
                "model": configuration["model"],
                "temperature": configuration["temperature"],
                "max_tokens": 128,
                "stream": True,
                "messages": [
                    {"role": "system", "content": "只输出JSON，reply用一句不超过30个汉字的话回答。"},
                    {"role": "user", "content": "请用一句话解释什么是RAG"},
                ],
                **extras,
            }
            first_content_ms: float | None = None
            reasoning_chunks = 0
            content = ""
            started = time.perf_counter()
            try:
                async with client.stream(
                    "POST",
                    configuration["base_url"].rstrip("/") + "/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {configuration['api_key']}"},
                ) as response:
                    if response.status_code >= 400:
                        print(name, "status", response.status_code, (await response.aread()).decode(errors="replace")[:240])
                        continue
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        chunk = json.loads(data)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        if delta.get("reasoning_content"):
                            reasoning_chunks += 1
                        text = delta.get("content")
                        if text:
                            if first_content_ms is None:
                                first_content_ms = (time.perf_counter() - started) * 1000
                            content += text
                total_ms = (time.perf_counter() - started) * 1000
                print(name, json.dumps({"first_content_ms": round(first_content_ms or -1, 2), "total_ms": round(total_ms, 2), "reasoning_chunks": reasoning_chunks, "content_chars": len(content)}, ensure_ascii=False))
            except Exception as exc:
                print(name, "error", type(exc).__name__, str(exc)[:240])


asyncio.run(main())
