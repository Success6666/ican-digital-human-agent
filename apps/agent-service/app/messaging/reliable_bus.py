"""Reliable presentation-message publication with RabbitMQ and local outbox fallback."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4


logger = logging.getLogger(__name__)


class ReliableMessageBus:
    def __init__(self, *, url: str = "", exchange: str = "ican.agent", queue: str = "digital-human.presentation.v2", outbox_path: str = "data/presentation-outbox.jsonl", timeout_seconds: float = 2.0, max_in_flight: int = 512, prefetch_count: int = 256, retry_limit: int = 3) -> None:
        self.url = url
        self.exchange_name = exchange
        self.queue_name = queue
        self.dead_letter_exchange = f"{exchange}.dlx"
        self.dead_letter_queue = f"{queue}.dead"
        self.outbox_path = Path(outbox_path)
        self.timeout_seconds = timeout_seconds
        self.max_in_flight = max(1, int(max_in_flight))
        self.prefetch_count = max(1, int(prefetch_count))
        self.retry_limit = max(0, int(retry_limit))
        self._connection: Any | None = None
        self._channel: Any | None = None
        self._exchange: Any | None = None
        self._lock = asyncio.Lock()
        self._publish_gate = asyncio.Semaphore(self.max_in_flight)

    async def publish(self, *, topic: str, payload: dict[str, Any]) -> str:
        envelope = {"messageId": uuid4().hex, "topic": topic, "createdAt": datetime.now(UTC).isoformat(), "payload": payload}
        if self.url:
            try:
                async with self._publish_gate:
                    await asyncio.wait_for(self._publish_rabbit(envelope), timeout=self.timeout_seconds)
                return envelope["messageId"]
            except Exception as exc:
                logger.warning("RabbitMQ presentation publish failed; writing message %s to outbox: %s", envelope["messageId"], type(exc).__name__)
        await asyncio.to_thread(self._append_outbox, envelope)
        return envelope["messageId"]

    async def _publish_rabbit(self, envelope: dict[str, Any]) -> None:
        try:
            import aio_pika
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("aio-pika is not installed") from exc
        async with self._lock:
            if self._connection is None or self._connection.is_closed:
                self._connection = await aio_pika.connect_robust(self.url)
                self._channel = None
                self._exchange = None
            if self._channel is None or self._channel.is_closed:
                channel = await self._connection.channel(publisher_confirms=True, on_return_raises=True)
                exchange = await channel.declare_exchange(self.exchange_name, aio_pika.ExchangeType.DIRECT, durable=True)
                dead_exchange = await channel.declare_exchange(self.dead_letter_exchange, aio_pika.ExchangeType.DIRECT, durable=True)
                dead_queue = await channel.declare_queue(
                    self.dead_letter_queue,
                    durable=True,
                    arguments={"x-queue-type": "quorum"},
                )
                await dead_queue.bind(dead_exchange, routing_key=envelope["topic"])
                queue = await channel.declare_queue(
                    self.queue_name,
                    durable=True,
                    arguments={
                        "x-dead-letter-exchange": self.dead_letter_exchange,
                        "x-dead-letter-routing-key": envelope["topic"],
                        "x-message-ttl": 86_400_000,
                        "x-max-length": 10_000,
                        "x-overflow": "reject-publish-dlx",
                        "x-queue-type": "quorum",
                    },
                )
                await queue.bind(exchange, routing_key=envelope["topic"])
                self._channel = channel
                self._exchange = exchange
            exchange = self._exchange
        message = aio_pika.Message(
            body=json.dumps(envelope, ensure_ascii=False).encode("utf-8"),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=envelope["messageId"],
            timestamp=datetime.fromisoformat(envelope["createdAt"]),
            type=envelope["topic"],
            headers={"x-idempotency-key": envelope["messageId"], "x-prefetch-count": self.prefetch_count},
        )
        await exchange.publish(message, routing_key=envelope["topic"], mandatory=True)

    def _append_outbox(self, envelope: dict[str, Any]) -> None:
        self.outbox_path.parent.mkdir(parents=True, exist_ok=True)
        with self.outbox_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(envelope, ensure_ascii=False) + "\n")

    async def close(self) -> None:
        connection = self._connection
        self._connection = None
        channel, self._channel = self._channel, None
        self._exchange = None
        if channel is not None and not channel.is_closed:
            await channel.close()
        if connection is not None and not connection.is_closed:
            await connection.close()
