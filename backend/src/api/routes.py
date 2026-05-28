import json
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from core import get_logger, settings
from core.metrics import metrics_registry
from db import Company, check_connection, get_db_session
from retrieval.retriever import build_filter_expr
from vectorstore import MilvusStore

from .auth import get_current_user
from .auth import router as auth_router
from .models import (
    Citation,
    HealthResponse,
    IngestStatusResponse,
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
ingest_tasks: dict[str, dict] = {}


def build_query_filters(request: QueryRequest, current_user) -> dict[str, str]:
    filters = {}
    if request.language:
        filters["language"] = request.language
    if request.category:
        filters["category"] = request.category
    if getattr(current_user, "company_id", None):
        filters["company_id"] = current_user.company_id
    if getattr(current_user, "id", None):
        filters["user_id"] = current_user.id
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

    ingest_tasks[task_id]["status"] = "running"
    try:
        pipeline = Pipeline()
        pipeline.register_defaults()

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

        index_stats = {"chunks": 0, "inserted": 0}
        if request.index and articles:
            index_stats = await index_articles(
                articles,
                user_id=user_id,
                company_id=company_id,
            )

        ingest_tasks[task_id].update({
            "status": "completed",
            "articles_collected": len(articles),
            "chunks_indexed": index_stats.get("chunks", 0),
            "records_inserted": index_stats.get("inserted", 0),
        })
        logger.info("ingestion_completed", task_id=task_id, source=request.source, articles=len(articles))
    except Exception as e:
        ingest_tasks[task_id].update({"status": "failed", "error": str(e)})
        metrics_registry.increment("rag_ingest_trigger_errors_total")
        logger.error("ingest_task_failed", task_id=task_id, source=request.source, error=str(e))


@router.post("/query")
async def query(request: QueryRequest, req: Request, current_user=Depends(get_current_user)):
    """
    Query endpoint with SSE streaming support.

    Returns sources first, then streams the answer token by token.
    """
    trace_id = req.state.trace_id
    metrics_registry.increment("rag_query_requests_total")
    filters = build_query_filters(request, current_user)

    logger.info("query_request_received",
        trace_id=trace_id,
        query=request.query,
        top_k=request.top_k,
        stream=request.stream,
    )

    if request.stream:
        # 流式路径：真正的 token 流
        from agent.graph import run_agent_stream

        async def stream_generator():
            try:
                async for event in run_agent_stream(
                    query=request.query,
                    trace_id=trace_id,
                    top_k=request.top_k,
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
        # 非流式路径：保持现有逻辑
        from agent import run_agent

        result = await run_agent(
            query=request.query,
            trace_id=trace_id,
            top_k=request.top_k,
            filters=filters,
        )

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
        sample_results = store.query(expr=build_current_user_expr(current_user), limit=10000)
        total = len(sample_results)

        sources: dict[str, int] = {}
        categories: dict[str, int] = {}
        languages: dict[str, int] = {}

        for r in sample_results:
            source = r.get("source", "unknown")
            category = r.get("category", "unknown")
            language = r.get("language", "unknown")

            sources[source] = sources.get(source, 0) + 1
            categories[category] = categories.get(category, 0) + 1
            languages[language] = languages.get(language, 0) + 1

        return StatsResponse(
            total_articles=total,
            sources=sources,
            categories=categories,
            languages=languages,
        )
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
async def ingest_trigger(
    request: IngestTriggerRequest,
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

        collector_name = request.source

        if collector_name:
            if collector_name not in pipeline.list_collectors():
                return IngestTriggerResponse(
                    status="error",
                    source=collector_name,
                    message=f"Collector '{collector_name}' not found",
                )

        quota_ok, quota_error = await reserve_company_quota(current_user)
        if not quota_ok:
            return IngestTriggerResponse(
                status="error",
                source=collector_name,
                message=quota_error or "quota exceeded",
            )

        task_id = f"ingest_{uuid.uuid4().hex[:12]}"
        ingest_tasks[task_id] = {
            "status": "pending",
            "source": collector_name,
            "user_id": getattr(current_user, "id", "") or "",
            "company_id": getattr(current_user, "company_id", "") or "",
            "articles_collected": 0,
            "chunks_indexed": 0,
            "records_inserted": 0,
        }
        background_tasks.add_task(
            run_ingest_task,
            task_id,
            request,
            ingest_tasks[task_id]["user_id"],
            ingest_tasks[task_id]["company_id"],
        )
        logger.info("ingestion_task_enqueued", task_id=task_id, source=collector_name)

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
            source=request.source,
            message=f"Ingestion failed: {e}",
        )


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
    except Exception as e:
        logger.error("ingest_status_failed", error=str(e))
        metrics_registry.increment("rag_ingest_status_errors_total")
        raise HTTPException(status_code=503, detail="Ingest status service unavailable") from e


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    """Prometheus-compatible metrics endpoint."""
    return PlainTextResponse(metrics_registry.render_prometheus(), media_type="text/plain")
