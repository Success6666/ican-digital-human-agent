"""Redis response cache with tenant-safe keys and in-process single-flight."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import re
import secrets
import unicodedata
from collections import OrderedDict
from typing import Any

from ..domain.models import ChatResult


class ResponseCache:
    def __init__(
        self,
        *,
        redis_url: str,
        key_prefix: str = "ican:agent",
        ttl_seconds: int = 300,
        max_bytes: int = 256_000,
        scope: str = "tenant",
        lock_seconds: int = 15,
        timeout_seconds: float = 0.25,
        max_entries: int = 100_000,
        local_cache_ttl_seconds: float = 5.0,
        local_cache_max_entries: int = 10_000,
    ) -> None:
        self.redis_url = redis_url
        self.key_prefix = key_prefix.rstrip(":") or "ican:agent"
        self.ttl_seconds = max(1, int(ttl_seconds))
        self.max_bytes = max(1024, int(max_bytes))
        self.scope = scope.strip().casefold() if scope else "tenant"
        self.lock_seconds = max(2, int(lock_seconds))
        self.timeout_seconds = max(0.05, float(timeout_seconds))
        self.max_entries = max(100, int(max_entries))
        self.local_cache_ttl_seconds = max(0.1, float(local_cache_ttl_seconds))
        self.local_cache_max_entries = max(100, int(local_cache_max_entries))
        self._redis: Any | None = None
        self._unavailable = False
        self._local: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._local_lock = asyncio.Lock()
        self._singleflight: dict[str, asyncio.Future[ChatResult]] = {}
        self._singleflight_lock = asyncio.Lock()
        # Strong references to fire-and-forget tasks (TTL refresh). The event
        # loop keeps only weak references, so holding these prevents an
        # in-flight refresh from being collected before it completes.
        self._background_tasks: set[asyncio.Task[Any]] = set()

    @staticmethod
    def normalize(message: str) -> str:
        normalized = unicodedata.normalize("NFKC", message)
        normalized = re.sub(r"\s+", " ", normalized).strip().casefold()
        return normalized[:4000]

    def key(self, *, tenant_id: str, user_id: str, message: str, model: str, profile_version: str = "0") -> str:
        owner = tenant_id if self.scope != "user" else f"{tenant_id}:{user_id}"
        digest = hashlib.sha256(
            "\x1f".join((owner, model[:128], profile_version[:64], self.normalize(message))).encode("utf-8")
        ).hexdigest()
        return f"{self.key_prefix}:answer:{digest}"

    async def _client(self) -> Any | None:
        if self._redis is not None:
            return self._redis
        if self._unavailable:
            return None
        try:
            from redis.asyncio import Redis

            client = Redis.from_url(self.redis_url, decode_responses=True)
            await asyncio.wait_for(client.ping(), timeout=self.timeout_seconds)
            self._redis = client
            return client
        except Exception:
            self._unavailable = True
            return None

    async def get(self, key: str) -> ChatResult | None:
        now = asyncio.get_running_loop().time()
        async with self._local_lock:
            item = self._local.get(key)
            if item and item[0] > now:
                self._local.move_to_end(key)
                self._local[key] = (now + self.local_cache_ttl_seconds, item[1])
                return self._decode(item[1])
            if item:
                self._local.pop(key, None)
        client = await self._client()
        raw: str | None = None
        if client is not None:
            try:
                raw = await asyncio.wait_for(client.get(key), timeout=self.timeout_seconds)
                if raw is not None:
                    self._remember_local(key, raw)
                    # Sliding TTL is maintained without adding another network
                    # round-trip to the request critical path. The task is
                    # retained because the event loop only holds a weak
                    # reference: without this the refresh can be collected
                    # mid-flight and the TTL silently stops sliding.
                    task = asyncio.create_task(self._refresh_ttl(client, key))
                    self._background_tasks.add(task)
                    task.add_done_callback(self._background_tasks.discard)
            except Exception:
                self._unavailable = True
        if not raw:
            return None
        return self._decode(raw)

    async def set(self, key: str, result: ChatResult) -> bool:
        raw = json.dumps(result.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
        encoded_size = len(raw.encode("utf-8"))
        if encoded_size > self.max_bytes:
            return False
        client = await self._client()
        if client is not None:
            try:
                await asyncio.wait_for(client.set(key, raw, ex=self.ttl_seconds), timeout=self.timeout_seconds)
                self._remember_local(key, raw)
                return True
            except Exception:
                self._unavailable = True
        self._remember_local(key, raw)
        return True

    def _remember_local(self, key: str, raw: str) -> None:
        self._local[key] = (asyncio.get_running_loop().time() + self.local_cache_ttl_seconds, raw)
        self._local.move_to_end(key)
        while len(self._local) > min(self.max_entries, self.local_cache_max_entries):
            self._local.popitem(last=False)

    async def _refresh_ttl(self, client: Any, key: str) -> None:
        try:
            await asyncio.wait_for(client.expire(key, self.ttl_seconds), timeout=self.timeout_seconds)
        except Exception:
            return

    @staticmethod
    def _decode(raw: str | None) -> ChatResult | None:
        if not raw:
            return None
        try:
            return ChatResult.model_validate(json.loads(raw))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    async def get_or_compute(self, key: str, compute: Any) -> tuple[ChatResult, bool]:
        cached = await self.get(key)
        if cached is not None:
            return cached, True
        # First collapse duplicates inside one worker.
        async with self._singleflight_lock:
            future = self._singleflight.get(key)
            owner = future is None
            if owner:
                future = asyncio.get_running_loop().create_future()
                self._singleflight[key] = future
        if not owner:
            return await future, True
        distributed_owner = False
        lock_token = secrets.token_hex(16)
        client = await self._client()
        lock_key = f"{key}:lock"
        if client is not None:
            try:
                distributed_owner = bool(await asyncio.wait_for(client.set(lock_key, lock_token, nx=True, ex=self.lock_seconds), timeout=self.timeout_seconds))
                if not distributed_owner:
                    deadline = asyncio.get_running_loop().time() + self.lock_seconds
                    while asyncio.get_running_loop().time() < deadline:
                        await asyncio.sleep(0.05)
                        cached = await self.get(key)
                        if cached is not None:
                            future.set_result(cached)
                            return cached, True
            except Exception:
                self._unavailable = True
        try:
            # A peer may have completed while the lock was being acquired.
            cached = await self.get(key)
            if cached is not None:
                future.set_result(cached)
                return cached, True
            result = await compute()
            if isinstance(result, ChatResult) and not result.interrupted and not result.tool_calls:
                await self.set(key, result)
            future.set_result(result)
            return result, False
        except BaseException as exc:
            if not future.done():
                future.set_exception(exc)
            raise
        finally:
            if distributed_owner and client is not None:
                with contextlib.suppress(Exception):
                    await client.eval("if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end", 1, lock_key, lock_token)
            async with self._singleflight_lock:
                self._singleflight.pop(key, None)

    async def close(self) -> None:
        client, self._redis = self._redis, None
        if client is not None:
            await client.aclose()


__all__ = ["ResponseCache"]
