"""Deep Research API - 研究任务入口"""
import asyncio
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from .auth import get_current_user
from ..db.database import get_db_session
from ..db.models import User, ResearchTask
from ..core import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/research", tags=["research"])


class ResearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=500, description="研究问题")
    output_format: str = Field(default="both", description="markdown/ppt/both")
    time_window: str = Field(default="last_3_months", description="last_1_month/last_3_months/last_6_months/all")
    top_k: int = Field(default=10, ge=1, le=100, description="每个子问题检索数量")


class ResearchResponse(BaseModel):
    task_id: str
    status: str  # "processing" | "completed" | "failed"
    message: str
    current_step: str | None = None  # planner/retriever/analyst/checker/writer
    plan: dict | None = None


async def _run_research_task(task_id: str, query: str, user_id: str, company_id: str | None):
    """后台执行完整研究流程（planner → retriever → analyst → checker → writer）"""
    from ..agent.research_graph import run_research

    try:
        logger.info("research_task_started", task_id=task_id)

        # 调用完整研究流程
        result = await run_research(query=query, user_id=user_id, company_id=company_id)

        final_output = result.get("final_output", {}) or {}
        evidence = result.get("evidence", [])
        report_md = final_output.get("report_md", "")

        # 更新完成状态
        async with get_db_session() as db:
            await db.execute(
                update(ResearchTask)
                .where(ResearchTask.id == task_id)
                .values(
                    status="completed",
                    result_markdown=report_md,
                    result_summary=report_md[:500] if report_md else "",
                    sources_used=len(evidence),
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
                    .values(status="failed", error_message=str(e))
                )
                await db.commit()
        except Exception:
            pass


@router.post("", response_model=ResearchResponse)
async def create_research(
    req: ResearchRequest,
    current_user: Annotated[User, Depends(get_current_user)],
):
    """
    创建研究任务（异步执行完整 pipeline）。

    流程：
    1. 创建 ResearchTask（status=processing）
    2. 触发 run_research() 后台执行
    3. 立即返回 task_id（不等待 LLM 完成）
    4. GET /api/research/{task_id} 轮询状态和结果
    """
    user = current_user
    task_id = f"task_{uuid.uuid4().hex[:12]}"

    logger.info("research_task_created", task_id=task_id, user_id=user.id, query=req.query)

    try:
        # 写入 research_tasks 表（初始状态为 processing）
        async with get_db_session() as db:
            task = ResearchTask(
                id=task_id,
                user_id=user.id,
                company_id=user.company_id,
                title=f"研究: {req.query[:50]}",
                query=req.query,
                status="processing",
            )
            db.add(task)
            await db.commit()

        # 启动后台任务执行完整研究流程
        asyncio.create_task(
            _run_research_task(task_id, req.query, user.id, user.company_id)
        )

        # 立即返回 task_id，不等待 LLM 完成
        return ResearchResponse(
            task_id=task_id,
            status="processing",
            message="研究任务已创建，正在异步处理中",
            current_step="planner",
            plan={
                "output_format": req.output_format,
                "time_window": req.time_window,
                "top_k": req.top_k,
            },
        )

    except Exception as e:
        logger.error("research_task_creation_failed", task_id=task_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


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
        "current_step": None,  # 当前 step 存储在 state 中，需要定期更新才能追踪
        "query": task.query,
        "title": task.title,
        "result_markdown": task.result_markdown,
        "result_summary": task.result_summary,
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
        "current_step": None,  # TODO: 可通过定期更新 ResearchTask.current_step 字段实现
        "sources_used": task.sources_used,
        "error_message": task.error_message,
    }