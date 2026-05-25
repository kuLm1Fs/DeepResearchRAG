from fastapi import APIRouter, Request, Response
from sse_starlette.sse import EventSourceResponse
import json

from core import get_logger, settings
from vectorstore import MilvusStore

from .models import QueryRequest, QueryResponse, StatsResponse, HealthResponse, Source, Citation, IngestTriggerRequest, IngestTriggerResponse, IngestStatusResponse
from .auth import router as auth_router
from .research import router as research_router

logger = get_logger(__name__)
router = APIRouter()
router.include_router(auth_router)
router.include_router(research_router)


@router.post("/query")
async def query(request: QueryRequest, req: Request):
    """
    Query endpoint with SSE streaming support.

    Returns sources first, then streams the answer token by token.
    """
    trace_id = req.state.trace_id

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
                ):
                    event_type = event["type"]
                    yield {
                        "event": event_type,
                        "data": json.dumps(event, ensure_ascii=False),
                    }
            except Exception as e:
                logger.error("stream_query_failed", error=str(e))
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
async def get_stats():
    """Get collection statistics."""
    try:
        store = MilvusStore()
        total = store.count()

        # Get sample to build stats (in production, maintain these counts in metadata)
        sample_results = store.query(expr="id >= 0", limit=10000)

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

        # Estimate totals based on sample
        if len(sample_results) > 0:
            ratio = total / len(sample_results)
            sources = {k: int(v * ratio) for k, v in sources.items()}
            categories = {k: int(v * ratio) for k, v in categories.items()}
            languages = {k: int(v * ratio) for k, v in languages.items()}

        return StatsResponse(
            total_articles=total,
            sources=sources,
            categories=categories,
            languages=languages,
        )
    except Exception as e:
        logger.error("stats_failed", error=str(e))
        return StatsResponse(
            total_articles=0,
            sources={},
            categories={},
            languages={},
        )


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    milvus_connected = False
    try:
        store = MilvusStore()
        store.count()
        milvus_connected = True
    except Exception as e:
        logger.warning("milvus_health_check_failed", error=str(e))

    return HealthResponse(
        status="healthy" if milvus_connected else "degraded",
        milvus_connected=milvus_connected,
        llm_provider=settings.llm_provider,
    )


@router.post("/ingest/trigger", response_model=IngestTriggerResponse)
async def ingest_trigger(request: IngestTriggerRequest):
    """
    Trigger data ingestion from specified source or all sources.

    This is an async trigger - collection happens in background.
    """
    from ingestion import Pipeline

    try:
        pipeline = Pipeline()
        pipeline.register_defaults()

        collector_name = request.source
        articles_collected = 0

        if collector_name:
            # Trigger specific collector
            if collector_name not in pipeline.list_collectors():
                return IngestTriggerResponse(
                    status="error",
                    source=collector_name,
                    message=f"Collector '{collector_name}' not found",
                )
            articles = list(pipeline.collect_one(collector_name, limit=request.limit))
        else:
            # Trigger all collectors
            articles = list(pipeline.collect_all(limit=request.limit))

        articles_collected = len(articles)
        logger.info("ingestion_completed", source=collector_name, articles=articles_collected)

        return IngestTriggerResponse(
            status="started",
            source=collector_name,
            message=f"Collected {articles_collected} articles",
            articles_collected=articles_collected,
        )
    except Exception as e:
        logger.error("ingest_trigger_failed", error=str(e))
        return IngestTriggerResponse(
            status="error",
            source=request.source,
            message=f"Ingestion failed: {e}",
        )


@router.get("/ingest/status", response_model=IngestStatusResponse)
async def ingest_status():
    """
    Get current ingestion status and data statistics.
    """
    from ingestion import Pipeline

    try:
        pipeline = Pipeline()
        pipeline.register_defaults()

        store = MilvusStore()
        total = store.count()

        # Get source breakdown from sample
        sample_results = store.query(expr="id >= 0", limit=1000)
        sources: dict[str, int] = {}
        for r in sample_results:
            source = r.get("source", "unknown")
            sources[source] = sources.get(source, 0) + 1

        # Estimate total per source
        if len(sample_results) > 0 and total > 0:
            ratio = total / len(sample_results)
            sources = {k: int(v * ratio) for k, v in sources.items()}

        return IngestStatusResponse(
            total_articles=total,
            sources=sources,
            collectors=pipeline.list_collectors(),
        )
    except Exception as e:
        logger.error("ingest_status_failed", error=str(e))
        return IngestStatusResponse(
            total_articles=0,
            sources={},
            collectors=[],
        )
