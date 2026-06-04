import asyncio
import unittest

from src.tasks.redis_queue import RedisTaskBroker
from src.tasks.reliable import (
    InMemoryReliableTaskQueue,
    ReliableTaskWorker,
    TaskCancelled,
    TaskStatus,
)


class ReliableTaskQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_heartbeats_and_completes_task(self):
        queue = InMemoryReliableTaskQueue()
        await queue.enqueue("task-1", {"query": "AI market"})
        seen = []

        async def handler(task, heartbeat):
            seen.append(task.task_id)
            await heartbeat("retriever")
            return {"report": "done"}

        worker = ReliableTaskWorker(queue, worker_id="worker-1", handler=handler)
        processed = await worker.run_once()

        task = await queue.get("task-1")
        self.assertTrue(processed)
        self.assertEqual(seen, ["task-1"])
        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertEqual(task.current_step, "completed")
        self.assertEqual(task.result, {"report": "done"})
        self.assertIsNotNone(task.heartbeat_at)

    async def test_worker_retries_failures_then_moves_to_dead_letter(self):
        queue = InMemoryReliableTaskQueue()
        await queue.enqueue("task-1", {"query": "AI market"}, max_attempts=2)

        async def handler(task, heartbeat):
            raise RuntimeError(f"boom-{task.attempt_count}")

        worker = ReliableTaskWorker(queue, worker_id="worker-1", handler=handler)

        self.assertTrue(await worker.run_once())
        task = await queue.get("task-1")
        self.assertEqual(task.status, TaskStatus.PENDING)
        self.assertEqual(task.attempt_count, 1)

        self.assertTrue(await worker.run_once())
        task = await queue.get("task-1")
        self.assertEqual(task.status, TaskStatus.DEAD_LETTER)
        self.assertEqual(task.attempt_count, 2)
        self.assertIn("boom-2", task.error_message)
        self.assertEqual(await queue.dead_letters(), ["task-1"])

    async def test_cancel_requested_task_is_not_executed(self):
        queue = InMemoryReliableTaskQueue()
        await queue.enqueue("task-1", {"query": "AI market"})
        await queue.cancel("task-1", reason="user requested")
        called = False

        async def handler(task, heartbeat):
            nonlocal called
            called = True

        worker = ReliableTaskWorker(queue, worker_id="worker-1", handler=handler)
        processed = await worker.run_once()

        task = await queue.get("task-1")
        self.assertTrue(processed)
        self.assertFalse(called)
        self.assertEqual(task.status, TaskStatus.CANCELLED)
        self.assertEqual(task.error_message, "user requested")

    async def test_cancel_during_execution_marks_task_cancelled(self):
        queue = InMemoryReliableTaskQueue()
        await queue.enqueue("task-1", {"query": "AI market"})

        async def handler(task, heartbeat):
            await queue.cancel(task.task_id, reason="stop now")
            await heartbeat("analyst")

        worker = ReliableTaskWorker(queue, worker_id="worker-1", handler=handler)

        with self.assertRaises(TaskCancelled):
            await worker.run_once(raise_cancelled=True)

        task = await queue.get("task-1")
        self.assertEqual(task.status, TaskStatus.CANCELLED)
        self.assertEqual(task.current_step, "cancelled")
        self.assertEqual(task.error_message, "stop now")

    async def test_stale_running_task_is_requeued_instead_of_lost(self):
        queue = InMemoryReliableTaskQueue(heartbeat_timeout_seconds=0.01)
        await queue.enqueue("task-1", {"query": "AI market"})
        task = await queue.reserve("worker-1")
        self.assertEqual(task.status, TaskStatus.RUNNING)

        await asyncio.sleep(0.02)
        reclaimed = await queue.reclaim_stale()

        task = await queue.get("task-1")
        self.assertEqual(reclaimed, ["task-1"])
        self.assertEqual(task.status, TaskStatus.PENDING)
        self.assertIsNone(task.locked_by)

    async def test_redis_broker_pushes_and_blocks_on_task_ids(self):
        class FakeRedis:
            def __init__(self):
                self.items = []

            async def rpush(self, key, value):
                self.items.append((key, value))

            async def blpop(self, keys, timeout=0):
                if not self.items:
                    return None
                key, value = self.items.pop(0)
                return key.encode(), value.encode()

        redis = FakeRedis()
        broker = RedisTaskBroker(redis, queue_name="research")

        await broker.enqueue("task-1")
        task_id = await broker.dequeue(timeout_seconds=1)

        self.assertEqual(task_id, "task-1")


if __name__ == "__main__":
    unittest.main()
