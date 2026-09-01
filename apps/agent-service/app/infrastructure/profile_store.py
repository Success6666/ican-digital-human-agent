"""Tenant/account scoped communication preferences."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any


class AccountPreferenceStore:
    """Small Redis-backed preference store with bounded local fallback."""

    _allowed = {"language", "tone", "voice", "verbosity", "constraints"}

    def __init__(self, *, redis_url: str, key_prefix: str, timeout_seconds: float = 0.25) -> None:
        self.redis_url = redis_url
        self.key_prefix = key_prefix.rstrip(":") or "ican:agent"
        self.timeout_seconds = max(0.05, float(timeout_seconds))
        self._redis: Any | None = None
        self._unavailable = False
        self._local: dict[str, dict[str, str]] = {}
        self._lock = asyncio.Lock()

    def _key(self, tenant_id: str, user_id: str) -> str:
        return f"{self.key_prefix}:profile:{_safe(tenant_id)}:{_safe(user_id)}"

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

    async def get(self, *, tenant_id: str, user_id: str) -> dict[str, str]:
        key = self._key(tenant_id, user_id)
        client = await self._client()
        if client is not None:
            try:
                raw = await asyncio.wait_for(client.get(key), timeout=self.timeout_seconds)
                if raw:
                    payload = json.loads(raw)
                    return _clean(payload)
            except Exception:
                self._unavailable = True
        async with self._lock:
            return dict(self._local.get(key, {}))

    async def update(self, *, tenant_id: str, user_id: str, values: dict[str, Any]) -> dict[str, str]:
        key = self._key(tenant_id, user_id)
        current = await self.get(tenant_id=tenant_id, user_id=user_id)
        current.update(_clean(values))
        encoded = json.dumps(current, ensure_ascii=False, separators=(",", ":"))
        client = await self._client()
        if client is not None:
            try:
                await asyncio.wait_for(client.set(key, encoded), timeout=self.timeout_seconds)
                return current
            except Exception:
                self._unavailable = True
        async with self._lock:
            self._local[key] = dict(current)
        return current

    async def close(self) -> None:
        client, self._redis = self._redis, None
        if client is not None:
            await client.aclose()


def _safe(value: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9._:-]", "_", str(value).strip())
    return clean[:128] or "default"


def _clean(values: Any) -> dict[str, str]:
    if not isinstance(values, dict):
        return {}
    result: dict[str, str] = {}
    for key, value in values.items():
        if str(key) not in AccountPreferenceStore._allowed or value is None:
            continue
        text = re.sub(r"[\x00-\x1f\x7f]", " ", str(value)).strip()
        if text:
            result[str(key)] = text[:512]
    return result


__all__ = ["AccountPreferenceStore"]
