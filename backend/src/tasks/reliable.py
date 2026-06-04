"""Reliable long-task queue primitives.

The production path can be backed by Redis/DB, but the state machine is kept
small and deterministic so it can be regression-tested without external
services: enqueue -> reserve -> heartbeat -> complete / retry / dead letter.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Protocol


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DEAD_LETTER = "dead_letter"


class TaskCancelled(RuntimeError):
    """Raised when a worker observes cancellation while executing a task."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass(slots=True)
class ReliableTask:
    task_id: str
    payload: dict[str, Any]
    status: TaskStatus = TaskStatus.PENDING
    current_step: str = "queued"
    attempt_count: int = 0
    max_attempts: int = 3
    locked_by: str | None = None
    heartbeat_at: datetime | None = None
    enqueued_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    result: dict[str, Any] | None = None
    error_message: str | None = None
    cancel_requested: bool = False
    cancel_reason: str | None = None


class ReliableQueue(Protocol):
    async def enqueue(
        self,
        task_id: str,
        payload: dict[str, Any],
        *,
        max_attempts: int = 3,
    ) -> ReliableTask:
        ...

    async def reserve(self, worker_id: str) -> ReliableTask | None:
        ...

    async def heartbeat(self, task_id: str, worker_id: str, step: str | None = None) -> ReliableTask:
        ...

    async def complete(self, task_id: str, worker_id: str, result: dict[str, Any] | None = None) -> ReliableTask:
        ...

    async def fail(self, task_id: str, worker_id: str, error: str) -> ReliableTask:
        ...

    async def cancel(self, task_id: str, reason: str = "cancelled") -> ReliableTask:
        ...

    async def get(self, task_id: str) -> ReliableTask:
        ...


class InMemoryReliableTaskQueue:
    """Redis-like FIFO queue for tests and local single-process development."""

    def __init__(self, *, heartbeat_timeout_seconds: float = 60.0) -> None:
        self.heartbeat_timeout = timedelta(seconds=heartbeat_timeout_seconds)
        self._tasks: dict[str, ReliableTask] = {}
        self._ready: list[str] = []
        self._dead_letters: list[str] = []
        self._lock = asyncio.Lock()

    async def enqueue(
        self,
        task_id: str,
        payload: dict[str, Any],
        *,
        max_attempts: int = 3,
    ) -> ReliableTask:
        async with self._lock:
            if task_id in self._tasks:
                raise ValueError(f"task already exists: {task_id}")
            task = ReliableTask(task_id=task_id, payload=payload, max_attempts=max_attempts)
            self._tasks[task_id] = task
            self._ready.append(task_id)
            return task

    async def reserve(self, worker_id: str) -> ReliableTask | None:
        async with self._lock:
            while self._ready:
                task_id = self._ready.pop(0)
                task = self._tasks[task_id]
                if task.status == TaskStatus.CANCELLED and task.cancel_requested:
                    task.locked_by = worker_id
                    task.updated_at = utcnow()
                    return task
                if task.status != TaskStatus.PENDING:
                    continue
                task.status = TaskStatus.RUNNING
                task.current_step = "running"
                task.locked_by = worker_id
                task.attempt_count += 1
                task.heartbeat_at = utcnow()
                task.updated_at = task.heartbeat_at
                return task
            return None

    async def heartbeat(self, task_id: str, worker_id: str, step: str | None = None) -> ReliableTask:
        async with self._lock:
            task = self._require_task(task_id)
            self._require_lock(task, worker_id)
            if task.cancel_requested:
                task.status = TaskStatus.CANCELLED
                task.current_step = "cancelled"
                task.locked_by = None
                task.error_message = task.cancel_reason or "cancelled"
                task.updated_at = utcnow()
                raise TaskCancelled(task.error_message)
            task.heartbeat_at = utcnow()
            task.updated_at = task.heartbeat_at
            if step:
                task.current_step = step
            return task

    async def complete(
        self,
        task_id: str,
        worker_id: str,
        result: dict[str, Any] | None = None,
    ) -> ReliableTask:
        async with self._lock:
            task = self._require_task(task_id)
            self._require_lock(task, worker_id)
            if task.cancel_requested:
                task.status = TaskStatus.CANCELLED
                task.current_step = "cancelled"
                task.error_message = task.cancel_reason or "cancelled"
            else:
                task.status = TaskStatus.COMPLETED
                task.current_step = "completed"
                task.result = result or {}
            task.locked_by = None
            task.updated_at = utcnow()
            return task

    async def fail(self, task_id: str, worker_id: str, error: str) -> ReliableTask:
        async with self._lock:
            task = self._require_task(task_id)
            self._require_lock(task, worker_id)
            task.error_message = error
            task.locked_by = None
            task.updated_at = utcnow()
            if task.cancel_requested:
                task.status = TaskStatus.CANCELLED
                task.current_step = "cancelled"
                task.error_message = task.cancel_reason or error
            elif task.attempt_count >= task.max_attempts:
                task.status = TaskStatus.DEAD_LETTER
                task.current_step = "dead_letter"
                if task.task_id not in self._dead_letters:
                    self._dead_letters.append(task.task_id)
            else:
                task.status = TaskStatus.PENDING
                task.current_step = "queued"
                self._ready.append(task.task_id)
            return task

    async def cancel(self, task_id: str, reason: str = "cancelled") -> ReliableTask:
        async with self._lock:
            task = self._require_task(task_id)
            task.cancel_requested = True
            task.cancel_reason = reason
            task.updated_at = utcnow()
            if task.status == TaskStatus.PENDING:
                task.status = TaskStatus.CANCELLED
                task.current_step = "cancelled"
                task.error_message = reason
            return task

    async def reclaim_stale(self) -> list[str]:
        async with self._lock:
            now = utcnow()
            reclaimed = []
            for task in self._tasks.values():
                if task.status != TaskStatus.RUNNING or task.heartbeat_at is None:
                    continue
                if now - task.heartbeat_at <= self.heartbeat_timeout:
                    continue
                task.status = TaskStatus.PENDING
                task.current_step = "queued"
                task.locked_by = None
                task.updated_at = now
                self._ready.append(task.task_id)
                reclaimed.append(task.task_id)
            return reclaimed

    async def get(self, task_id: str) -> ReliableTask:
        async with self._lock:
            return self._require_task(task_id)

    async def dead_letters(self) -> list[str]:
        async with self._lock:
            return list(self._dead_letters)

    def _require_task(self, task_id: str) -> ReliableTask:
        try:
            return self._tasks[task_id]
        except KeyError as exc:
            raise KeyError(f"task not found: {task_id}") from exc

    @staticmethod
    def _require_lock(task: ReliableTask, worker_id: str) -> None:
        if task.locked_by != worker_id:
            raise RuntimeError(f"task {task.task_id} is not locked by {worker_id}")


Heartbeat = Callable[[str | None], Awaitable[None]]
TaskHandler = Callable[[ReliableTask, Heartbeat], Awaitable[dict[str, Any] | None]]


class ReliableTaskWorker:
    def __init__(self, queue: ReliableQueue, *, worker_id: str, handler: TaskHandler) -> None:
        self.queue = queue
        self.worker_id = worker_id
        self.handler = handler

    async def run_once(self, *, raise_cancelled: bool = False) -> bool:
        task = await self.queue.reserve(self.worker_id)
        if task is None:
            return False

        if task.cancel_requested:
            await self.queue.cancel(task.task_id, task.cancel_reason or "cancelled")
            return True

        async def heartbeat(step: str | None = None) -> None:
            await self.queue.heartbeat(task.task_id, self.worker_id, step)

        try:
            result = await self.handler(task, heartbeat)
            await self.queue.complete(task.task_id, self.worker_id, result)
        except TaskCancelled:
            if raise_cancelled:
                raise
        except Exception as exc:
            await self.queue.fail(task.task_id, self.worker_id, str(exc))
        return True
