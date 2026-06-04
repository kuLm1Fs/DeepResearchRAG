"""Reliable Deep Research task queue and worker."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, update

from core import get_logger, settings
from core.degradation import DegradationPolicy
from core.fault_injection import FaultInjectedError, FaultInjector
from db.database import get_db_session
from db.models import ResearchTask
from tasks.reliable import TaskCancelled, TaskStatus, utcnow

logger = get_logger(__name__)


async def enqueue_research_task(task_id: str) -> None:
    """Publish a research task id to the queue.

    The database row is the durable source of truth. Redis can be used as a
    wake-up channel in production, but a worker can always recover by polling
    pending/stale DB rows, which is what prevents task loss.
    """
    if not settings.redis_url:
        logger.info("research_task_enqueued_db_only", task_id=task_id)
        return

    try:
        from redis.asyncio import from_url

        from tasks.redis_queue import RedisTaskBroker

        redis = from_url(settings.redis_url, decode_responses=False)
        broker = RedisTaskBroker(redis, queue_name=settings.research_queue_name)
        await broker.enqueue(task_id)
        await redis.aclose()
        logger.info("research_task_enqueued_redis", task_id=task_id)
    except Exception as exc:
        # DB state is durable; Redis is a wake-up signal. If broker publish
        # fails, polling workers can still find the pending task.
        logger.warning("research_task_redis_enqueue_failed", task_id=task_id, error=str(exc))


async def reserve_research_task(worker_id: str, heartbeat_timeout_seconds: int = 120) -> ResearchTask | None:
    """Reserve one pending or stale running research task for this worker."""
    stale_before = utcnow() - timedelta(seconds=heartbeat_timeout_seconds)
    async with get_db_session() as db:
        result = await db.execute(
            select(ResearchTask)
            .where(
                (ResearchTask.status == TaskStatus.PENDING.value)
                | (
                    (ResearchTask.status == TaskStatus.RUNNING.value)
                    & (
                        (ResearchTask.heartbeat_at.is_(None))
                        | (ResearchTask.heartbeat_at < stale_before)
                    )
                )
            )
            .order_by(ResearchTask.created_at)
            .limit(1)
        )
        task = result.scalar_one_or_none()
        if task is None:
            return None

        await db.execute(
            update(ResearchTask)
            .where(ResearchTask.id == task.id)
            .values(
                status=TaskStatus.RUNNING.value,
                current_step="running",
                attempt_count=(task.attempt_count or 0) + 1,
                locked_by=worker_id,
                heartbeat_at=func.now(),
                started_at=func.coalesce(ResearchTask.started_at, func.now()),
            )
        )
        await db.commit()
        task.status = TaskStatus.RUNNING.value
        task.current_step = "running"
        task.attempt_count = (task.attempt_count or 0) + 1
        task.locked_by = worker_id
        return task


async def heartbeat_research_task(task_id: str, worker_id: str, step: str | None = None) -> None:
    async with get_db_session() as db:
        result = await db.execute(
            select(ResearchTask.cancel_requested_at)
            .where(ResearchTask.id == task_id, ResearchTask.locked_by == worker_id)
        )
        cancel_requested_at = result.scalar_one_or_none()
        if cancel_requested_at is not None:
            await db.execute(
                update(ResearchTask)
                .where(ResearchTask.id == task_id)
                .values(
                    status=TaskStatus.CANCELLED.value,
                    current_step="cancelled",
                    locked_by=None,
                    error_message="用户取消",
                    completed_at=func.now(),
                )
            )
            await db.commit()
            raise TaskCancelled("用户取消")

        values: dict[str, Any] = {"heartbeat_at": func.now()}
        if step:
            values["current_step"] = step
        await db.execute(
            update(ResearchTask)
            .where(ResearchTask.id == task_id, ResearchTask.locked_by == worker_id)
            .values(**values)
        )
        await db.commit()


async def complete_research_task(
    task_id: str,
    worker_id: str,
    result: dict[str, Any],
) -> None:
    final_output = result.get("final_output", {}) or result
    final_data = final_output.get("data", final_output) if isinstance(final_output, dict) else {}
    evidence = result.get("evidence", [])
    report_md = final_data.get("report_md", "")

    async with get_db_session() as db:
        await db.execute(
            update(ResearchTask)
            .where(ResearchTask.id == task_id, ResearchTask.locked_by == worker_id)
            .values(
                status=TaskStatus.COMPLETED.value,
                current_step="completed",
                locked_by=None,
                result_markdown=report_md,
                result_summary=report_md[:500] if report_md else "",
                result_slides=final_data.get("slides"),
                ppt_outline=final_data.get("ppt_outline"),
                evidence_trace=result.get("evidence_trace") or None,
                quality_report=result.get("quality_report") or None,
                execution_log=result.get("execution_log") or None,
                memory_snapshot=result.get("memory_snapshot") or None,
                sources_used=len(evidence),
                gaps_identified=result.get("gaps") or None,
                conflicts_detected=result.get("conflicts") or None,
                completed_at=func.now(),
            )
        )
        await db.commit()


async def fail_or_retry_research_task(task_id: str, worker_id: str, error: str) -> str:
    async with get_db_session() as db:
        result = await db.execute(
            select(ResearchTask.attempt_count, ResearchTask.max_attempts, ResearchTask.cancel_requested_at)
            .where(ResearchTask.id == task_id, ResearchTask.locked_by == worker_id)
        )
        row = result.one_or_none()
        if row is None:
            return TaskStatus.FAILED.value

        attempt_count, max_attempts, cancel_requested_at = row
        if cancel_requested_at is not None:
            status = TaskStatus.CANCELLED.value
            values = {
                "status": status,
                "current_step": "cancelled",
                "locked_by": None,
                "error_message": "用户取消",
                "completed_at": func.now(),
            }
        elif (attempt_count or 0) >= (max_attempts or 3):
            status = TaskStatus.DEAD_LETTER.value
            values = {
                "status": status,
                "current_step": "dead_letter",
                "locked_by": None,
                "error_message": error,
                "dead_letter_reason": error,
                "completed_at": func.now(),
            }
        else:
            status = TaskStatus.PENDING.value
            values = {
                "status": status,
                "current_step": "queued",
                "locked_by": None,
                "error_message": error,
            }

        await db.execute(update(ResearchTask).where(ResearchTask.id == task_id).values(**values))
        await db.commit()
        return status


async def run_research_worker_once(worker_id: str, heartbeat_timeout_seconds: int = 120) -> bool:
    task = await reserve_research_task(worker_id, heartbeat_timeout_seconds)
    if task is None:
        return False

    from agent.research_graph import run_research

    async def on_step(step: str, state: dict) -> None:
        await heartbeat_research_task(task.id, worker_id, step)

    try:
        await heartbeat_research_task(task.id, worker_id, "started")
        fault_injector = FaultInjector.from_settings(settings)
        await fault_injector.maybe_delay("worker")
        try:
            fault_injector.maybe_raise("worker")
        except FaultInjectedError as exc:
            DegradationPolicy.from_settings(settings).decide(
                component="worker",
                failure=exc.scenario,
            )
            raise
        result = await run_research(
            query=task.query or "",
            task_id=task.id,
            user_id=task.user_id or "",
            company_id=task.company_id,
            on_step=on_step,
            return_state=True,
        )
        await complete_research_task(task.id, worker_id, result)
        logger.info("research_task_completed", task_id=task.id, worker_id=worker_id)
    except TaskCancelled:
        logger.info("research_task_cancelled", task_id=task.id, worker_id=worker_id)
        raise
    except Exception as exc:
        status = await fail_or_retry_research_task(task.id, worker_id, str(exc))
        logger.warning("research_task_failed", task_id=task.id, worker_id=worker_id, status=status, error=str(exc))
    return True


async def requeue_stale_research_tasks(heartbeat_timeout_seconds: int = 120) -> int:
    stale_before = utcnow() - timedelta(seconds=heartbeat_timeout_seconds)
    async with get_db_session() as db:
        result = await db.execute(
            update(ResearchTask)
            .where(
                ResearchTask.status == TaskStatus.RUNNING.value,
                (ResearchTask.heartbeat_at.is_(None)) | (ResearchTask.heartbeat_at < stale_before),
            )
            .values(status=TaskStatus.PENDING.value, current_step="queued", locked_by=None)
        )
        await db.commit()
        return result.rowcount or 0
