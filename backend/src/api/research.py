"""Deep Research API - 研究任务入口"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from .auth import get_current_user
from ..db.database import get_db_session
from ..db.models import User, ResearchTask
from ..agent.research_tools import planner, retriever
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
    status: str
    message: str
    plan: dict | None = None


@router.post("", response_model=ResearchResponse)
async def create_research(
    req: ResearchRequest,
    current_user: Annotated[User, Depends(get_current_user)],
):
    """
    创建研究任务（同步执行 planner + retriever）。

    流程：
    1. 调用 planner 生成研究计划
    2. 调用 retriever 获取证据
    3. 写入 research_tasks 表
    4. 返回 task_id
    """
    user = current_user
    task_id = f"task_{uuid.uuid4().hex[:12]}"

    logger.info("research_task_created", task_id=task_id, user_id=user.id, query=req.query)

    try:
        # Step 1: Planner
        plan_result = planner(query=req.query, user_id=user.id)
        if plan_result["status"] != "success":
            raise HTTPException(status_code=500, detail=f"Planner 失败: {plan_result['errors']}")

        plan_data = plan_result["data"]
        sub_questions = plan_data.get("sub_questions", [req.query])
        logger.info("planner_completed", task_id=task_id, sub_questions=len(sub_questions))

        # Step 2: Retriever
        ret_result = retriever(sub_questions=sub_questions, top_k=req.top_k, user_id=user.id)
        evidence_count = ret_result["data"]["total_count"] if ret_result["data"] else 0
        logger.info("retriever_completed", task_id=task_id, evidence_count=evidence_count)

        # Step 3: 写入 DB（使用实际存在的字段）
        async with get_db_session() as db:
            task = ResearchTask(
                id=task_id,
                user_id=user.id,
                company_id=user.company_id,
                title=f"研究: {req.query[:50]}",  # title 是 required
                query=req.query,
                status="completed",
                result_summary=f"Planner 生成了 {len(sub_questions)} 个子问题，Retriever 返回 {evidence_count} 条证据",
                result_markdown="\n".join([
                    f"## 证据 {i+1}: {e['title']}"
                    for i, e in enumerate(ret_result["data"]["evidence"][:20]) if ret_result["data"]
                ]) if ret_result["data"] and ret_result["data"]["evidence"] else "Retriever 返回空结果",
                sources_used=evidence_count,
                started_at=None,  # 简化版不同步记录
            )
            db.add(task)
            await db.commit()

        return ResearchResponse(
            task_id=task_id,
            status="completed",
            message=f"Planner 生成了 {len(sub_questions)} 个子问题，Retriever 返回 {evidence_count} 条证据",
            plan={
                "goals": plan_data.get("goals", []),
                "audience": plan_data.get("audience", ""),
                "output_format": plan_data.get("output_format", req.output_format),
                "time_window": plan_data.get("time_window", req.time_window),
                "sub_questions": sub_questions,
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("research_task_failed", task_id=task_id, error=str(e))
        try:
            async with get_db_session() as db:
                task = ResearchTask(
                    id=task_id,
                    user_id=user.id,
                    company_id=user.company_id,
                    title=f"研究: {req.query[:50]}",
                    query=req.query,
                    status="failed",
                    error_message=str(e),
                )
                db.add(task)
                await db.commit()
        except Exception:
            pass  # DB write failed, already logged

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
        "query": task.query,
        "title": task.title,
        "result": task.result_markdown,
        "sources_used": task.sources_used,
        "error_message": task.error_message,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }