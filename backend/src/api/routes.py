from fastapi import APIRouter, Request, Response
from sse_starlette.sse import EventSourceResponse
import json

from core import get_logger, settings
from vectorstore import MilvusStore

from .models import QueryRequest, QueryResponse, StatsResponse, HealthResponse, Source

logger = get_logger(__name__)
router = APIRouter()


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

    from ..agent import run_agent

    # Run agent synchronously (could be made async with proper async LLM calls)
    result = await run_agent(
        query=request.query,
        trace_id=trace_id,
        top_k=request.top_k,
    )

    answer = result.get("answer", "")
    sources = result.get("sources", [])

    async def event_generator():
        # Send sources first
        sources_data = [Source(**s) if isinstance(s, dict) else s for s in sources]
        yield {
            "event": "sources",
            "data": json.dumps({"type": "sources", "data": [s.model_dump() for s in sources_data]}),
        }

        # Stream answer tokens
        if request.stream:
            # Simple tokenization (in production, use proper token streaming from LLM)
            words = answer.split()
            for i, word in enumerate(words):
                yield {
                    "event": "token",
                    "data": json.dumps({
                        "type": "token",
                        "data": word + (" " if i < len(words) - 1 else ""),
                    }),
                }

        # Send done
        response = QueryResponse(
            answer=answer,
            sources=[Source(**s) if isinstance(s, dict) else s for s in sources],
            trace_id=trace_id,
        )
        yield {
            "event": "done",
            "data": json.dumps({"type": "done", "data": response.model_dump()}),
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