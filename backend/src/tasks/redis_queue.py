"""Redis queue broker for reliable tasks.

Redis is intentionally used as a broker/wake-up queue, not as the only source
of truth. Durable task state stays in Postgres so a worker can recover by
polling pending/stale DB rows even if Redis loses an in-flight notification.
"""

from __future__ import annotations

from typing import Any


class RedisTaskBroker:
    def __init__(self, redis: Any, *, queue_name: str = "research") -> None:
        self.redis = redis
        self.queue_key = f"rag:tasks:{queue_name}:ready"

    async def enqueue(self, task_id: str) -> None:
        await self.redis.rpush(self.queue_key, task_id)

    async def dequeue(self, *, timeout_seconds: int = 5) -> str | None:
        item = await self.redis.blpop([self.queue_key], timeout=timeout_seconds)
        if item is None:
            return None
        _key, value = item
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)
