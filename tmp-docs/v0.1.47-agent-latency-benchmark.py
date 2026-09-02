"""Agent 本地热路径分段延迟基准，区分缓存命中与真实图运行。"""

from __future__ import annotations

import asyncio
import json
import statistics
import time
from pathlib import Path
from types import SimpleNamespace

import sys

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "apps" / "agent-service"
sys.path.insert(0, str(SERVICE))

from app.application.chat_service import ChatApplicationService  # noqa: E402
from app.domain.models import ChatResult  # noqa: E402
from app.infrastructure.response_cache import ResponseCache  # noqa: E402


class FakeSessions:
    def __init__(self) -> None:
        self.record = SimpleNamespace(active_run_id=None)

    async def get_for_user(self, *, user_id: str, session_id: str):
        return self.record

    async def begin_run(self, *, user_id: str, session_id: str) -> str:
        self.record.active_run_id = f"run-{time.perf_counter_ns()}"
        return self.record.active_run_id


class FakeGraph:
    async def invoke(self, **kwargs):
        await asyncio.sleep(0)
        return ChatResult(reply="本地 Agent 热路径响应", trace_id="trace", session_id=kwargs["session_id"], run_id=kwargs["run_id"], provider="mock")


async def main() -> None:
    cache = ResponseCache(redis_url="redis://127.0.0.1:6399/0", ttl_seconds=30)
    service = ChatApplicationService(
        graph=FakeGraph(),
        sessions=FakeSessions(),
        profile_store=None,
        response_cache=cache,
    )
    cold: list[float] = []
    warm: list[float] = []
    for index in range(20):
        started = time.perf_counter()
        await service.send(user_id="u", user_name="用户", session_id=f"s-{index}", message=f"问题 {index}", tenant_id="t")
        cold.append((time.perf_counter() - started) * 1000)
    for index in range(20):
        started = time.perf_counter()
        await service.send(user_id="u", user_name="用户", session_id=f"s-warm-{index}", message=f"问题 {index}", tenant_id="t")
        warm.append((time.perf_counter() - started) * 1000)
    result = {
        "version": "0.1.47",
        "generatedAt": "2026-09-02",
        "samples": 20,
        "metrics": {
            "firstRequestP50Ms": round(statistics.median(cold), 3),
            "firstRequestP95Ms": round(sorted(cold)[18], 3),
            "nearCacheP50Ms": round(statistics.median(warm), 3),
            "nearCacheP95Ms": round(sorted(warm)[18], 3),
        },
        "raw": {"firstRequestMs": cold, "nearCacheMs": warm},
    }
    output = ROOT / "tmp-docs" / "agent-evaluations"
    output.mkdir(parents=True, exist_ok=True)
    (output / "v0.1.47-agent-latency.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
