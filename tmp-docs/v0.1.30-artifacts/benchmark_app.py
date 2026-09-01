from __future__ import annotations

import json
import time

import httpx


def benchmark(message: str) -> None:
    with httpx.Client(base_url="http://127.0.0.1:8088", timeout=90.0) as client:
        response = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        response.raise_for_status()
        session = client.post("/api/sessions", json={}).json()["sessionId"]
        started = time.perf_counter()
        first_delta_ms = None
        done = None
        with client.stream("POST", "/api/chat/stream", json={"sessionId": session, "message": message}) as stream:
            stream.raise_for_status()
            for line in stream.iter_lines():
                if not line.startswith("data:"):
                    continue
                payload = json.loads(line[5:].strip())
                elapsed_ms = (time.perf_counter() - started) * 1000
                if payload.get("text") and payload.get("phase") is None and first_delta_ms is None:
                    first_delta_ms = elapsed_ms
                if payload.get("reply") is not None:
                    done = payload
                    print(
                        json.dumps(
                            {
                                "message": message,
                                "first_delta_ms": round(first_delta_ms or -1, 2),
                                "wall_ms": round(elapsed_ms, 2),
                                "agent_latency_ms": payload.get("agentLatencyMs"),
                                "digital_human_latency_ms": payload.get("digitalHumanLatencyMs"),
                                "reply": payload.get("reply"),
                                "tool_count": len(payload.get("toolCalls", [])),
                            },
                            ensure_ascii=False,
                        )
                    )
        if done is None:
            raise RuntimeError("stream ended without done")


benchmark("你是谁？")
benchmark("请用一句话解释什么是RAG")
