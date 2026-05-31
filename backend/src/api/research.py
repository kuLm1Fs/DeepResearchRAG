"""Deep Research API - 研究任务入口"""
import asyncio
import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from .auth import get_current_user
from ..core import get_logger, write_audit_log
from ..db.database import get_db_session
from ..db.models import User, ResearchTask

logger = get_logger(__name__)
router = APIRouter(prefix="/research", tags=["research"])

# Track in-flight research tasks to prevent GC before completion
_active_tasks: set[asyncio.Task] = set()


class ResearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=500, description="研究问题")
    output_format: str = Field(default="both", description="markdown/ppt/both")
    time_window: str = Field(default="last_3_months", description="last_1_month/last_3_months/last_6_months/all")
    top_k: int = Field(default=10, ge=1, le=100, description="每个子问题检索数量")


class ResearchResponse(BaseModel):
    task_id: str
    status: str  # "pending" | "running" | "completed" | "failed"
    message: str
    current_step: str | None = None  # planner/retriever/analyst/checker/writer
    plan: dict | None = None


async def _run_research_task(task_id: str, query: str, user_id: str, company_id: str | None):
    """后台执行完整研究流程（planner → retriever → analyst → checker → writer）"""
    from ..agent.research_graph import run_research

    async def on_step(step: str, state: dict):
        async with get_db_session() as db:
            await db.execute(
                update(ResearchTask)
                .where(ResearchTask.id == task_id)
                .values(
                    status="running",
                    current_step=step,
                    started_at=func.coalesce(ResearchTask.started_at, func.now()),
                )
            )
            await db.commit()

    try:
        logger.info("research_task_started", task_id=task_id)

        # 调用完整研究流程
        result = await run_research(
            query=query,
            task_id=task_id,
            user_id=user_id,
            company_id=company_id,
            on_step=on_step,
            return_state=True,
        )

        final_output = result.get("final_output", {}) or result
        final_data = final_output.get("data", final_output) if isinstance(final_output, dict) else {}
        evidence = result.get("evidence", [])
        report_md = final_data.get("report_md", "")

        # 更新完成状态
        async with get_db_session() as db:
            await db.execute(
                update(ResearchTask)
                .where(ResearchTask.id == task_id)
                .values(
                    status="completed",
                    current_step="completed",
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

        logger.info("research_task_completed", task_id=task_id, sources=len(evidence))

    except Exception as e:
        logger.error("research_task_failed", task_id=task_id, error=str(e))
        try:
            async with get_db_session() as db:
                await db.execute(
                    update(ResearchTask)
                    .where(ResearchTask.id == task_id)
                    .values(status="failed", current_step="failed", error_message=str(e))
                )
                await db.commit()
        except Exception as update_err:
            logger.error("research_task_failure_status_update_failed", task_id=task_id, error=str(update_err))


@router.post("", response_model=ResearchResponse)
async def create_research(
    req: ResearchRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_user)],
):
    """
    创建研究任务（异步执行完整 pipeline）。

    流程：
    1. 创建 ResearchTask（status=running）
    2. 触发 run_research() 后台执行
    3. 立即返回 task_id（不等待 LLM 完成）
    4. GET /api/research/{task_id} 轮询状态和结果
    """
    user = current_user
    task_id = f"task_{uuid.uuid4().hex[:12]}"

    logger.info("research_task_created", task_id=task_id, user_id=user.id, query=req.query)

    try:
        # 并发限制：检查当前 running 任务数
        MAX_CONCURRENT_RESEARCH = 3
        async with get_db_session() as db:
            result = await db.execute(
                select(func.count()).where(ResearchTask.status == "running")
            )
            running_count = result.scalar() or 0

        if running_count >= MAX_CONCURRENT_RESEARCH:
            logger.warning("research_concurrency_limit", running=running_count)
            raise HTTPException(
                status_code=429,
                detail=f"Too many concurrent research tasks ({running_count}/{MAX_CONCURRENT_RESEARCH}). Please wait for existing tasks to complete.",
            )

        # 写入 research_tasks 表（初始状态为 running）
        async with get_db_session() as db:
            task = ResearchTask(
                id=task_id,
                user_id=user.id,
                company_id=user.company_id,
                title=f"研究: {req.query[:50]}",
                query=req.query,
                status="running",
                current_step="queued",
            )
            db.add(task)
            await db.commit()

        # 启动后台任务执行完整研究流程
        task_ref = asyncio.create_task(
            _run_research_task(task_id, req.query, user.id, user.company_id)
        )
        _active_tasks.add(task_ref)
        task_ref.add_done_callback(_active_tasks.discard)

        background_tasks.add_task(
            write_audit_log,
            action="research.create",
            user_id=user.id,
            company_id=user.company_id,
            resource_type="research",
            resource_id=task_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            details={"query": req.query, "output_format": req.output_format},
        )

        # 立即返回 task_id，不等待 LLM 完成
        return ResearchResponse(
            task_id=task_id,
            status="running",
            message="研究任务已创建，正在异步处理中",
            current_step="queued",
            plan={
                "output_format": req.output_format,
                "time_window": req.time_window,
                "top_k": req.top_k,
            },
        )

    except Exception as e:
        logger.error("research_task_creation_failed", task_id=task_id, error=str(e))
        raise HTTPException(status_code=500, detail="研究任务创建失败")


@router.get("/{task_id}")
async def get_research(task_id: str, current_user: Annotated[User, Depends(get_current_user)]):
    """查询研究任务状态和结果"""
    async with get_db_session() as db:
        stmt = select(ResearchTask).where(
            ResearchTask.id == task_id,
            ResearchTask.user_id == current_user.id,
        )
        result = await db.execute(stmt)
        task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    return {
        "task_id": task.id,
        "status": task.status,
        "current_step": task.current_step,
        "query": task.query,
        "title": task.title,
        "result_markdown": task.result_markdown,
        "result_summary": task.result_summary,
        "result_slides": task.result_slides,
        "ppt_outline": task.ppt_outline,
        "evidence_trace": task.evidence_trace,
        "quality_report": task.quality_report,
        "execution_log": task.execution_log,
        "gaps_identified": task.gaps_identified,
        "conflicts_detected": task.conflicts_detected,
        "sources_used": task.sources_used,
        "error_message": task.error_message,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


@router.get("/{task_id}/status")
async def get_research_status(task_id: str, current_user: Annotated[User, Depends(get_current_user)]):
    """查询研究任务当前步骤进度"""
    async with get_db_session() as db:
        stmt = select(ResearchTask).where(
            ResearchTask.id == task_id,
            ResearchTask.user_id == current_user.id,
        )
        result = await db.execute(stmt)
        task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    return {
        "task_id": task.id,
        "status": task.status,
        "current_step": task.current_step,
        "sources_used": task.sources_used,
        "error_message": task.error_message,
    }


@router.post("/{task_id}/cancel")
async def cancel_research(task_id: str, current_user: Annotated[User, Depends(get_current_user)]):
    """取消正在运行的研究任务"""
    async with get_db_session() as db:
        stmt = select(ResearchTask).where(
            ResearchTask.id == task_id,
            ResearchTask.user_id == current_user.id,
        )
        result = await db.execute(stmt)
        task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task.status not in ("running", "pending"):
        raise HTTPException(status_code=400, detail=f"任务已{task.status}，无法取消")

    # Update DB status — research_graph checks this to detect cancellation
    async with get_db_session() as db:
        await db.execute(
            update(ResearchTask)
            .where(ResearchTask.id == task_id)
            .values(status="failed", current_step="failed", error_message="用户取消")
        )
        await db.commit()

    logger.info("research_task_cancelled", task_id=task_id)
    return {"task_id": task_id, "status": "failed", "message": "任务已取消"}


@router.get("/{task_id}/events")
async def stream_research_events(task_id: str, current_user: Annotated[User, Depends(get_current_user)]):
    """SSE stream for research progress, logs, report and PPT outline preview."""

    async def event_generator():
        last_payload = None
        while True:
            async with get_db_session() as db:
                stmt = select(ResearchTask).where(
                    ResearchTask.id == task_id,
                    ResearchTask.user_id == current_user.id,
                )
                result = await db.execute(stmt)
                task = result.scalar_one_or_none()

            if not task:
                yield {"event": "error", "data": '{"type":"error","data":"任务不存在"}'}
                return

            payload = {
                "type": "progress",
                "task_id": task.id,
                "status": task.status,
                "current_step": task.current_step,
                "execution_log": task.execution_log or [],
                "quality_report": task.quality_report,
                "result_markdown": task.result_markdown,
                "ppt_outline": task.ppt_outline,
                "sources_used": task.sources_used,
                "error_message": task.error_message,
                "gaps_identified": task.gaps_identified,
                "conflicts_detected": task.conflicts_detected,
            }
            if payload != last_payload:
                import json

                yield {"event": "progress", "data": json.dumps(payload, ensure_ascii=False, default=str)}
                last_payload = payload

            if task.status in ("completed", "failed"):
                return
            await asyncio.sleep(1)

    return EventSourceResponse(event_generator())
