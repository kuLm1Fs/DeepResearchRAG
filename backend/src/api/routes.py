import json
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sse_starlette.sse import EventSourceResponse

from core import get_logger, settings, write_audit_log, RAGError
from core.metrics import metrics_registry
from db import Company, check_connection, get_db_session
from db.models import Feedback, IngestTask
from retrieval.retriever import build_filter_expr
from vectorstore import MilvusStore

from .app import limiter
from .auth import get_current_user
from .auth import router as auth_router
from .models import (
    Citation,
    FeedbackRequest,
    FeedbackResponse,
    FeedbackStatsResponse,
    HealthResponse,
    IngestStatusResponse,
    IngestTaskResponse,
    IngestTriggerRequest,
    IngestTriggerResponse,
    QueryRequest,
    QueryResponse,
    Source,
    StatsResponse,
)
from .research import router as research_router

logger = get_logger(__name__)
router = APIRouter()
router.include_router(auth_router)
router.include_router(research_router)


def build_query_filters(request: QueryRequest, current_user) -> dict[str, Any]:
    filters: dict[str, Any] = {}
    if request.language:
        filters["language"] = request.language
    if request.category:
        filters["category"] = request.category
    if getattr(current_user, "company_id", None):
        filters["company_id"] = current_user.company_id
    if getattr(current_user, "id", None):
        filters["user_id"] = current_user.id
    if request.date_from is not None:
        filters["published_at_from"] = request.date_from
    if request.date_to is not None:
        filters["published_at_to"] = request.date_to
    return filters


def build_current_user_filters(current_user) -> dict[str, str]:
    filters = {}
    if getattr(current_user, "company_id", None):
        filters["company_id"] = current_user.company_id
    if getattr(current_user, "id", None):
        filters["user_id"] = current_user.id
    return filters


def build_current_user_expr(current_user) -> str:
    return build_filter_expr(build_current_user_filters(current_user)) or "id >= 0"


async def reserve_company_quota(current_user, units: int = 1) -> tuple[bool, str | None]:
    company_id = getattr(current_user, "company_id", None)
    if not company_id:
        return False, "Current user is not associated with a company"

    async with get_db_session() as db:
        result = await db.execute(select(Company).where(Company.id == company_id))
        company = result.scalar_one_or_none()
        if not company:
            return False, "Company not found"

        if company.quota_used + units > company.quota_limit:
            return False, "quota exceeded"

        company.quota_used += units
        return True, None


async def run_ingest_task(
    task_id: str,
    request: IngestTriggerRequest,
    user_id: str,
    company_id: str,
) -> None:
    from ingestion import Pipeline, index_articles
    from sqlalchemy import update as sql_update

    async with get_db_session() as db:
        await db.execute(
            sql_update(IngestTask).where(IngestTask.id == task_id).values(status="running")
        )
        await db.commit()

    try:
        pipeline = Pipeline()
        pipeline.register_defaults()

        try:
            if request.source:
                articles = list(
                    pipeline.collect_one(
                        request.source,
                        limit=request.limit,
                        fetch_full_text=request.fetch_full_text,
                    )
                )
            else:
                articles = list(
                    pipeline.collect_all(
                        limit=request.limit,
                        fetch_full_text=request.fetch_full_text,
                    )
                )
        finally:
            pipeline.shutdown()

        index_stats = {"chunks": 0, "inserted": 0}
        if request.index and articles:
            index_stats = await index_articles(
                articles,
                user_id=user_id,
                company_id=company_id,
            )

        async with get_db_session() as db:
            await db.execute(
                sql_update(IngestTask).where(IngestTask.id == task_id).values(
                    status="completed",
                    articles_collected=len(articles),
                    chunks_indexed=index_stats.get("chunks", 0),
                    records_inserted=index_stats.get("inserted", 0),
                    finished_at=func.now(),
                )
            )
            await db.commit()
        logger.info("ingestion_completed", task_id=task_id, source=request.source, articles=len(articles))
    except Exception as e:
        async with get_db_session() as db:
            await db.execute(
                sql_update(IngestTask).where(IngestTask.id == task_id).values(
                    status="failed", error=str(e), finished_at=func.now()
                )
            )
            await db.commit()
        metrics_registry.increment("rag_ingest_trigger_errors_total")
        logger.error("ingest_task_failed", task_id=task_id, source=request.source, error=str(e))


@router.post("/query")
@limiter.limit(settings.rate_limit_query)
async def query(body: QueryRequest, request: Request, background_tasks: BackgroundTasks, current_user=Depends(get_current_user)):
    """
    Query endpoint with SSE streaming support.

    Returns sources first, then streams the answer token by token.
    """
    trace_id = request.state.trace_id
    metrics_registry.increment("rag_query_requests_total")
    filters = build_query_filters(body, current_user)

    logger.info("query_request_received",
        trace_id=trace_id,
        query=body.query,
        top_k=body.top_k,
        stream=body.stream,
    )

    background_tasks.add_task(
        write_audit_log,
        action="query.execute",
        user_id=current_user.id,
        company_id=current_user.company_id,
        resource_type="query",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        details={"query": body.query, "top_k": body.top_k, "stream": body.stream},
    )

    if body.stream:
        # 流式路径：真正的 token 流
        from agent.graph import run_agent_stream

        async def stream_generator():
            try:
                async for event in run_agent_stream(
                    query=body.query,
                    trace_id=trace_id,
                    top_k=body.top_k,
                    filters=filters,
                ):
                    event_type = event["type"]
                    yield {
                        "event": event_type,
                        "data": json.dumps(event, ensure_ascii=False),
                    }
            except Exception as e:
                logger.error("stream_query_failed", error=str(e))
                metrics_registry.increment("rag_query_errors_total")
                yield {
                    "event": "error",
                    "data": json.dumps({"type": "error", "data": str(e)}, ensure_ascii=False),
                }

        return EventSourceResponse(stream_generator())
    else:
        # 非流式路径
        from agent import run_agent

        try:
            result = await run_agent(
                query=body.query,
                trace_id=trace_id,
                top_k=body.top_k,
                filters=filters,
            )
        except Exception as e:
            logger.error("non_stream_query_failed", trace_id=trace_id, error=str(e))
            metrics_registry.increment("rag_query_errors_total")

            async def error_generator():
                yield {
                    "event": "error",
                    "data": json.dumps({"type": "error", "data": str(e)}, ensure_ascii=False),
                }

            return EventSourceResponse(error_generator())

        answer = result.get("answer", "")
        sources = result.get("sources", [])
        citations = result.get("citations", [])

        async def event_generator():
            sources_data = [Source(**s) if isinstance(s, dict) else s for s in sources]
            citations_data = [Citation(**c) if isinstance(c, dict) else c for c in citations]
            yield {
                "event": "sources",
                "data": json.dumps({"type": "sources", "data": [s.model_dump() for s in sources_data]}, ensure_ascii=False),
            }
            response = QueryResponse(
                answer=answer,
                sources=sources_data,
                trace_id=trace_id,
                citations=citations_data,
            )
            yield {
                "event": "done",
                "data": json.dumps({"type": "done", "data": response.model_dump()}, ensure_ascii=False),
            }

        return EventSourceResponse(event_generator())


@router.get("/stats", response_model=StatsResponse)
async def get_stats(current_user=Depends(get_current_user)):
    """Get collection statistics."""
    try:
        metrics_registry.increment("rag_stats_requests_total")
        store = MilvusStore()

        # Get tenant-scoped sample to build stats.
        sample_results = store.query(
            expr=build_current_user_expr(current_user),
            limit=10000,
            output_fields=["source", "category", "language", "parent_doc_id"],
        )
        total = len(sample_results)

        # Count unique articles by parent_doc_id
        parent_ids: set[str] = set()
        sources: dict[str, int] = {}
        categories: dict[str, int] = {}
        languages: dict[str, int] = {}

        for r in sample_results:
            source = r.get("source", "unknown")
            category = r.get("category", "unknown")
            language = r.get("language", "unknown")
            parent_doc_id = r.get("parent_doc_id", "")

            if parent_doc_id:
                parent_ids.add(parent_doc_id)

            sources[source] = sources.get(source, 0) + 1
            categories[category] = categories.get(category, 0) + 1
            languages[language] = languages.get(language, 0) + 1

        # If no parent_doc_id, each record is an article (pre-chunking data)
        total_articles = len(parent_ids) if parent_ids else total

        return StatsResponse(
            total_articles=total_articles,
            total_chunks=total,
            sources=sources,
            categories=categories,
            languages=languages,
        )
    except RAGError as e:
        logger.error("stats_failed", error=str(e))
        metrics_registry.increment("rag_stats_errors_total")
        raise HTTPException(status_code=503, detail="Stats service unavailable") from e
    except Exception as e:
        logger.error("stats_failed", error=str(e))
        metrics_registry.increment("rag_stats_errors_total")
        raise HTTPException(status_code=503, detail="Stats service unavailable") from e


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    metrics_registry.increment("rag_health_requests_total")
    milvus_connected = False
    postgres_connected = False
    try:
        store = MilvusStore()
        store.count()
        milvus_connected = True
    except Exception as e:
        logger.warning("milvus_health_check_failed", error=str(e))

    try:
        postgres_connected = await check_connection()
    except Exception as e:
        logger.warning("postgres_health_check_failed", error=str(e))

    return HealthResponse(
        status="healthy" if milvus_connected and postgres_connected else "degraded",
        milvus_connected=milvus_connected,
        postgres_connected=postgres_connected,
        llm_provider=settings.llm_provider,
    )


@router.get("/livez")
async def livez():
    """Liveness check: the API process is alive."""
    return {"status": "alive"}


@router.get("/readyz", response_model=HealthResponse)
async def readyz():
    """Readiness check: dependencies needed to serve traffic are reachable."""
    return await health_check()


@router.post("/ingest/trigger", response_model=IngestTriggerResponse)
@limiter.limit(settings.rate_limit_ingest)
async def ingest_trigger(
    body: IngestTriggerRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user),
):
    """
    Trigger data ingestion from specified source or all sources.

    This is an async trigger - collection happens in background.
    """
    from ingestion import Pipeline

    try:
        metrics_registry.increment("rag_ingest_trigger_requests_total")
        pipeline = Pipeline()
        pipeline.register_defaults()

        collector_name = body.source

        try:
            if collector_name:
                if collector_name not in pipeline.list_collectors():
                    return IngestTriggerResponse(
                        status="error",
                        source=collector_name,
                        message=f"Collector '{collector_name}' not found",
                    )
        finally:
            pipeline.shutdown()

        quota_ok, quota_error = await reserve_company_quota(current_user)
        if not quota_ok:
            return IngestTriggerResponse(
                status="error",
                source=collector_name,
                message=quota_error or "quota exceeded",
            )

        task_id = f"ingest_{uuid.uuid4().hex[:12]}"
        user_id = getattr(current_user, "id", "") or ""
        company_id = getattr(current_user, "company_id", "") or ""

        async with get_db_session() as db:
            db.add(IngestTask(
                id=task_id,
                status="pending",
                source=collector_name,
                user_id=user_id,
                company_id=company_id,
            ))
            await db.commit()

        background_tasks.add_task(
            run_ingest_task,
            task_id,
            body,
            user_id,
            company_id,
        )
        logger.info("ingestion_task_enqueued", task_id=task_id, source=collector_name)

        background_tasks.add_task(
            write_audit_log,
            action="ingest.trigger",
            user_id=current_user.id,
            company_id=current_user.company_id,
            resource_type="ingest",
            resource_id=task_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            details={"source": collector_name},
        )

        return IngestTriggerResponse(
            status="started",
            source=collector_name,
            message=f"Ingestion task {task_id} started",
            task_id=task_id,
        )
    except Exception as e:
        logger.error("ingest_trigger_failed", error=str(e))
        metrics_registry.increment("rag_ingest_trigger_errors_total")
        return IngestTriggerResponse(
            status="error",
            source=body.source,
            message="数据采集失败",
        )


@router.get("/ingest/task/{task_id}", response_model=IngestTaskResponse)
async def ingest_task_status(task_id: str, current_user=Depends(get_current_user)):
    """Get status of a specific ingestion task."""
    async with get_db_session() as db:
        result = await db.execute(select(IngestTask).where(IngestTask.id == task_id))
        task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    # Only allow the task owner (or same company) to view status
    user_id = getattr(current_user, "id", "")
    company_id = getattr(current_user, "company_id", "")
    if task.user_id != user_id and task.company_id != company_id:
        raise HTTPException(status_code=403, detail="Access denied")
    return IngestTaskResponse(
        task_id=task_id,
        status=task.status,
        source=task.source,
        articles_collected=task.articles_collected,
        chunks_indexed=task.chunks_indexed,
        records_inserted=task.records_inserted,
        error=task.error,
    )


@router.get("/ingest/tasks", response_model=list[IngestTaskResponse])
async def ingest_task_list(current_user=Depends(get_current_user)):
    """List ingestion tasks for the current user/company (last 50)."""
    user_id = getattr(current_user, "id", "")
    company_id = getattr(current_user, "company_id", "")

    async with get_db_session() as db:
        result = await db.execute(
            select(IngestTask)
            .where(
                (IngestTask.user_id == user_id) | (IngestTask.company_id == company_id)
            )
            .order_by(IngestTask.created_at.desc())
            .limit(50)
        )
        tasks = result.scalars().all()

    return [
        IngestTaskResponse(
            task_id=t.id,
            status=t.status,
            source=t.source,
            articles_collected=t.articles_collected,
            chunks_indexed=t.chunks_indexed,
            records_inserted=t.records_inserted,
            error=t.error,
        )
        for t in tasks
    ]


@router.get("/ingest/status", response_model=IngestStatusResponse)
async def ingest_status(current_user=Depends(get_current_user)):
    """
    Get current ingestion status and data statistics.
    """
    from ingestion import Pipeline

    try:
        metrics_registry.increment("rag_ingest_status_requests_total")
        pipeline = Pipeline()
        pipeline.register_defaults()

        try:
            store = MilvusStore()

            # Get tenant-scoped source breakdown from sample.
            sample_results = store.query(expr=build_current_user_expr(current_user), limit=1000)
            total = len(sample_results)
            sources: dict[str, int] = {}
            for r in sample_results:
                source = r.get("source", "unknown")
                sources[source] = sources.get(source, 0) + 1

            return IngestStatusResponse(
                total_articles=total,
                sources=sources,
                collectors=pipeline.list_collectors(),
            )
        finally:
            pipeline.shutdown()
    except RAGError as e:
        logger.error("ingest_status_failed", error=str(e))
        metrics_registry.increment("rag_ingest_status_errors_total")
        raise HTTPException(status_code=503, detail="Ingest status service unavailable") from e
    except Exception as e:
        logger.error("ingest_status_failed", error=str(e))
        metrics_registry.increment("rag_ingest_status_errors_total")
        raise HTTPException(status_code=503, detail="Ingest status service unavailable") from e


@router.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    body: FeedbackRequest,
    current_user=Depends(get_current_user),
):
    """Submit user feedback on a query answer."""
    user_id = getattr(current_user, "id", "")
    company_id = getattr(current_user, "company_id", None)

    async with get_db_session() as db:
        fb = Feedback(
            query_id=body.query_id,
            query_text=body.query_text,
            rating=body.rating,
            reason=body.reason,
            comment=body.comment,
            user_id=user_id,
            company_id=company_id,
        )
        db.add(fb)
        await db.commit()
        await db.refresh(fb)

    metrics_registry.increment(f"rag_feedback_{body.rating}_total")
    logger.info("feedback_submitted", rating=body.rating, reason=body.reason, user_id=user_id)

    return FeedbackResponse(id=fb.id)


@router.get("/feedback/stats", response_model=FeedbackStatsResponse)
async def get_feedback_stats(current_user=Depends(get_current_user)):
    """Get aggregated feedback statistics for the current company."""
    company_id = getattr(current_user, "company_id", None)
    user_id = getattr(current_user, "id", "")

    async with get_db_session() as db:
        # Scope to company if available, otherwise user
        if company_id:
            result = await db.execute(
                select(Feedback).where(Feedback.company_id == company_id)
            )
        else:
            result = await db.execute(
                select(Feedback).where(Feedback.user_id == user_id)
            )
        feedbacks = result.scalars().all()

    total = len(feedbacks)
    positive = sum(1 for f in feedbacks if f.rating == "positive")
    negative = total - positive
    rate = positive / total if total > 0 else 0.0

    # Count negative reasons
    reasons: dict[str, int] = {}
    for f in feedbacks:
        if f.rating == "negative" and f.reason:
            reasons[f.reason] = reasons.get(f.reason, 0) + 1

    return FeedbackStatsResponse(
        total=total,
        positive=positive,
        negative=negative,
        satisfaction_rate=round(rate, 4),
        top_negative_reasons=dict(sorted(reasons.items(), key=lambda x: -x[1])[:5]),
    )


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    """Prometheus-compatible metrics endpoint."""
    return PlainTextResponse(metrics_registry.render_prometheus(), media_type="text/plain")
