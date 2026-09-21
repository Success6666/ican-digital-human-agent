"""Sharded Redis session store.

Each session is an independent Redis key. Lifecycle transitions use a
per-session lease, so unrelated tenants do not serialize behind one global
JSON document.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from ..domain.models import AvatarSession, SessionRecord, SessionStatus
from .session_close import SessionCloseLifecycleMixin
from .session_expiry import SessionExpiryMixin
from .session_store import InMemorySessionStore


class RedisSessionStore(InMemorySessionStore):
    def __init__(self, *, redis_url: str, key_prefix: str = "ican:agent", operation_timeout_seconds: float = 0.25, **kwargs: Any) -> None:
        super().__init__(cleanup_outbox_path=None, **kwargs)
        self.redis_url = redis_url
        self.key_prefix = key_prefix.rstrip(":") or "ican:agent"
        self.operation_timeout_seconds = max(0.05, float(operation_timeout_seconds))
        self._redis: Any | None = None
        self._redis_unavailable = False

    def _session_key(self, session_id: str) -> str:
        return f"{self.key_prefix}:session:{session_id}"

    @property
    def _state_key(self) -> str:
        """Compatibility marker for older integration fixtures."""
        return f"{self.key_prefix}:sessions"

    def _user_key(self, user_id: str) -> str:
        return f"{self.key_prefix}:user-sessions:{user_id}"

    def _lease_key(self, session_id: str) -> str:
        return f"{self.key_prefix}:lease:{session_id}"

    async def _client(self) -> Any | None:
        if self._redis is not None:
            return self._redis
        if self._redis_unavailable:
            return None
        try:
            from redis.asyncio import Redis
            client = Redis.from_url(self.redis_url, decode_responses=True)
            await asyncio.wait_for(client.ping(), timeout=self.operation_timeout_seconds)
            self._redis = client
            return client
        except Exception:
            self._redis_unavailable = True
            return None

    async def _load(self, client: Any, session_id: str) -> SessionRecord | None:
        raw = await asyncio.wait_for(client.get(self._session_key(session_id)), timeout=self.operation_timeout_seconds)
        if not raw:
            self._items.pop(session_id, None)
            return None
        try:
            record = SessionRecord.model_validate(json.loads(raw))
        except Exception:
            return None
        self._items[session_id] = record
        claim = await client.get(f"{self.key_prefix}:close-claim:{session_id}")
        if claim:
            self._closing.add(session_id)
            self._close_claims[session_id] = str(claim)
        else:
            self._closing.discard(session_id)
            self._close_claims.pop(session_id, None)
        return record

    async def _persist(self, client: Any, session_id: str) -> None:
        record = self._items.get(session_id)
        key = self._session_key(session_id)
        if record is None:
            await client.delete(key)
            return
        ttl = max(1, int((record.session.expires_at - datetime.now(UTC)).total_seconds()))
        await client.setex(key, ttl, json.dumps(record.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")))
        await client.sadd(self._user_key(record.session.user_id), session_id)
        claim_key = f"{self.key_prefix}:close-claim:{session_id}"
        claim = self._close_claims.get(session_id)
        if session_id in self._closing and claim:
            await client.setex(claim_key, ttl, claim)
        else:
            await client.delete(claim_key)

    async def _with_lease(self, session_id: str, operation: Callable[[], Any]) -> Any:
        client = await self._client()
        if client is None:
            return await operation()
        lease = client.lock(
            self._lease_key(session_id),
            timeout=max(1.0, self.operation_timeout_seconds * 8),
            blocking_timeout=self.operation_timeout_seconds,
            thread_local=False,
        )
        acquired = False
        started = False
        try:
            acquired = await lease.acquire()
            if not acquired:
                await asyncio.sleep(min(0.05, self.operation_timeout_seconds))
                acquired = await lease.acquire()
            if not acquired:
                return await operation()
            await self._load(client, session_id)
            started = True
            result = await operation()
            await self._persist(client, session_id)
            return result
        except Exception:
            self._redis_unavailable = True
            if not started:
                return await operation()
            raise
        finally:
            if acquired:
                with contextlib.suppress(Exception):
                    await lease.release()

    async def close_redis(self) -> None:
        client, self._redis = self._redis, None
        if client is not None:
            await client.aclose()

    async def create(self, session: AvatarSession) -> None:
        await self._with_lease(session.session_id, lambda: SessionExpiryMixin.create(self, session))

    async def get(self, session_id: str) -> SessionRecord | None:
        client = await self._client()
        if client is None:
            return await InMemorySessionStore.get(self, session_id)
        try:
            record = await self._load(client, session_id)
            if record is None:
                return None
            if record.session.status not in {SessionStatus.CLOSED, SessionStatus.EXPIRED} and record.session.expires_at <= datetime.now(UTC):
                return None
            return record.model_copy(deep=True)
        except Exception:
            self._redis_unavailable = True
            return await InMemorySessionStore.get(self, session_id)

    async def _mutate(self, session_id: str, method: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        return await self._with_lease(session_id, lambda: method(self, session_id, *args, **kwargs))

    async def touch(self, session_id: str, now: datetime | None = None, **kwargs: Any) -> bool:
        return await self._mutate(session_id, InMemorySessionStore.touch, now, **kwargs)

    async def begin_run(self, session_id: str, run_id: str | None = None) -> str | None:
        return await self._mutate(session_id, InMemorySessionStore.begin_run, run_id)

    async def is_interrupted(self, session_id: str, run_id: str | None = None) -> bool:
        record = await self.get(session_id)
        if record is None or record.session.status in {SessionStatus.CLOSED, SessionStatus.EXPIRED}:
            return True
        return bool(record.interrupted or (run_id is not None and record.active_run_id != run_id))

    async def mark_interrupted(self, session_id: str, run_id: str | None = None) -> SessionRecord | None:
        return await self._mutate(session_id, InMemorySessionStore.mark_interrupted, run_id)

    async def heartbeat(self, session_id: str, run_id: str | None = None, now: datetime | None = None) -> bool:
        return await self.touch(session_id, now, run_id=run_id, clear_interrupt=False)

    async def wait_for_stop(self, session_id: str, run_id: str) -> None:
        while not await self.is_interrupted(session_id, run_id):
            await asyncio.sleep(0.05)

    async def claim_close_token(self, session_id: str) -> str | None:
        return await self._mutate(session_id, SessionCloseLifecycleMixin.claim_close_token)

    async def is_closing(self, session_id: str) -> bool:
        client = await self._client()
        if client is not None:
            try:
                return bool(await client.exists(f"{self.key_prefix}:close-claim:{session_id}"))
            except Exception:
                self._redis_unavailable = True
        return session_id in self._closing

    async def wait_for_close(self, session_id: str) -> None:
        while await self.is_closing(session_id):
            await asyncio.sleep(0.05)

    async def abort_close(self, session_id: str, *, claim_token: str | None = None) -> SessionRecord | None:
        return await self._mutate(session_id, SessionCloseLifecycleMixin.abort_close, claim_token=claim_token)

    async def complete_close(self, session_id: str, *, claim_token: str | None = None) -> SessionRecord | None:
        return await self._mutate(session_id, SessionCloseLifecycleMixin.complete_close, claim_token=claim_token)

    async def close(self, session_id: str) -> SessionRecord | None:
        return await self._mutate(session_id, SessionCloseLifecycleMixin.close)

    async def claim_expired_cleanup(self, session_id: str, generation_id: str | None) -> bool:
        return await self._mutate(session_id, SessionExpiryMixin.claim_expired_cleanup, generation_id)

    async def finish_expired_cleanup(self, session_id: str, generation_id: str | None) -> None:
        return await self._mutate(session_id, SessionExpiryMixin.finish_expired_cleanup, generation_id)

    async def requeue_expired(self, record: SessionRecord) -> bool:
        return await self._with_lease(record.session.session_id, lambda: SessionExpiryMixin.requeue_expired(self, record))

    async def remove_expired(self, now: datetime | None = None, *, limit: int | None = None) -> list[SessionRecord]:
        client = await self._client()
        if client is None:
            return await SessionExpiryMixin.remove_expired(self, now, limit=limit)
        expired: list[SessionRecord] = []
        batch = limit or self.cleanup_batch_size
        async for key in client.scan_iter(match=f"{self.key_prefix}:session:*"):
            if len(expired) >= batch:
                break
            session_id = key.rsplit(":", 1)[-1]
            record = await self.get(session_id)
            if record is not None and record.session.expires_at <= (now or datetime.now(UTC)):
                record.session.status = SessionStatus.EXPIRED
                await client.delete(self._session_key(session_id), f"{self.key_prefix}:close-claim:{session_id}")
                await client.srem(self._user_key(record.session.user_id), session_id)
                self._items.pop(session_id, None)
                expired.append(record)
        return expired

    async def list_for_user(self, user_id: str, *, limit: int = 100) -> list[SessionRecord]:
        client = await self._client()
        if client is None:
            return await InMemorySessionStore.list_for_user(self, user_id, limit=limit)
        try:
            ids = await client.smembers(self._user_key(user_id))
            result: list[SessionRecord] = []
            for session_id in list(ids)[: max(1, min(limit, 10_000))]:
                record = await self.get(str(session_id))
                if record is not None:
                    result.append(record)
            return result
        except Exception:
            self._redis_unavailable = True
            return await InMemorySessionStore.list_for_user(self, user_id, limit=limit)

    async def size(self) -> int:
        client = await self._client()
        if client is None:
            return await InMemorySessionStore.size(self)
        count = 0
        async for _ in client.scan_iter(match=f"{self.key_prefix}:session:*"):
            count += 1
        return count

    async def stats(self) -> dict[str, int]:
        base = await super().stats()
        base["redis_sharded"] = 1
        base["redis_session_count"] = await self.size()
        return base


__all__ = ["RedisSessionStore"]
