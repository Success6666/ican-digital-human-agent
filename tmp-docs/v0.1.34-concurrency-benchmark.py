"""Lightweight connection-level benchmark for the Agent health endpoint."""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time

import httpx


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000/api/health")
    parser.add_argument("--concurrency", type=int, default=10_000)
    args = parser.parse_args()
    limits = httpx.Limits(max_connections=args.concurrency, max_keepalive_connections=min(args.concurrency, 512))
    timeout = httpx.Timeout(10.0, connect=5.0)
    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        started = time.perf_counter()
        samples: list[float] = []

        async def one() -> int:
            t0 = time.perf_counter()
            response = await client.get(args.url)
            samples.append((time.perf_counter() - t0) * 1000)
            return response.status_code

        statuses: list[object] = []
        # Batch scheduling avoids exhausting the benchmark host's ephemeral
        # ports while still maintaining a 10k request sample.
        for start in range(0, args.concurrency, 500):
            statuses.extend(await asyncio.gather(*(one() for _ in range(min(500, args.concurrency - start))), return_exceptions=True))
    valid = [item for item in statuses if isinstance(item, int)]
    samples.sort()
    p95 = samples[min(len(samples) - 1, int(len(samples) * 0.95))] if samples else 0
    print({"requests": args.concurrency, "ok": sum(item == 200 for item in valid), "errors": len(statuses) - len(valid), "p50_ms": round(statistics.median(samples), 2) if samples else None, "p95_ms": round(p95, 2), "wall_ms": round((time.perf_counter() - started) * 1000, 2)})


if __name__ == "__main__":
    asyncio.run(main())
