"""Phase 5: Knowledge graph introspection API.

Endpoints (all mounted under ``/api/graph`` by routes.py):

  GET  /stats            — node counts by label + top-10 most-mentioned entities
  GET  /entity/{name}    — 1-hop neighborhood of an entity (name OR entity_id)
  GET  /related/{chunk}  — entities that mention a chunk + their intra-chunk relations
  POST /rebuild          — async-trigger a graph rebuild (re-extract from Milvus)

All endpoints degrade gracefully when Neo4j is disabled or unreachable —
graph retrieval is best-effort, the vector path is the source of truth.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import GraphStoreError, get_logger, settings

from .auth import get_current_user
from .models import (
    GraphEntityRef,
    GraphEntitySubgraph,
    GraphRebuildResponse,
    GraphRelationRef,
    GraphStatsResponse,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/graph", tags=["graph"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _open_store_or_none():
    """Return a Neo4jStore instance, or None if graph layer is disabled.

    We do not raise on import/init failure here — the API surface should
    degrade to a 503 with a clear message rather than 500. Callers handle
    the None case uniformly.
    """
    if not getattr(settings, "graph_enabled", True):
        return None
    # Tolerate the same dual-import quirk as runtime.create_graph_retriever
    try:
        from graph.neo4j_store import Neo4jStore
    except ModuleNotFoundError:
        try:
            from src.graph.neo4j_store import Neo4jStore
        except ModuleNotFoundError:
            return None
    try:
        return Neo4jStore()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "graph_store_init_failed",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/stats", response_model=GraphStatsResponse)
async def graph_stats(current_user=Depends(get_current_user)):
    """Return graph node/edge counts plus the top-mentioned entities.

    Used by the sidebar graph panel to show the user what's in the graph
    even when they haven't run a query yet.
    """
    store = _open_store_or_none()
    if store is None:
        return GraphStatsResponse(enabled=False, counts={}, top_entities=[])

    try:
        counts, top = await asyncio.gather(store.stats(), store.top_entities(limit=10))
    except GraphStoreError as exc:
        logger.warning("graph_stats_failed", error=str(exc))
        return GraphStatsResponse(enabled=True, counts={}, top_entities=[])

    return GraphStatsResponse(
        enabled=True,
        counts=counts,
        top_entities=[GraphEntityRef(**e) for e in top],
    )


@router.get("/entity/{name}", response_model=GraphEntitySubgraph)
async def entity_subgraph(name: str, current_user=Depends(get_current_user)):
    """Return the 1-hop neighborhood of an entity for the graph viewer.

    ``name`` matches on either the canonical entity name or the entity_id;
    we don't enforce type matching here because the frontend usually has
    just a name string (e.g. from the graph_facts SSE event).
    """
    store = _open_store_or_none()
    if store is None:
        raise HTTPException(status_code=503, detail="Graph layer disabled or unreachable")

    try:
        result = await store.entity_subgraph(name=name)
    except GraphStoreError as exc:
        logger.warning("entity_subgraph_failed", name=name, error=str(exc))
        raise HTTPException(status_code=503, detail=f"Graph query failed: {exc}") from exc

    if not result:
        raise HTTPException(status_code=404, detail=f"Entity '{name}' not found")

    # Normalize: Neo4j driver returns lists of dicts that may contain
    # `None` entries from the OPTIONAL MATCH arms; drop those.
    raw_relations = [r for r in (result.get("relations") or []) if r and r.get("target_id")]
    return GraphEntitySubgraph(
        entity_id=result["entity_id"],
        name=result.get("name") or name,
        type=result.get("type"),
        description=result.get("description"),
        mention_count=result.get("mention_count"),
        relations=[GraphRelationRef(**r) for r in raw_relations],
        sample_chunks=result.get("sample_chunks") or [],
    )


@router.get("/related/{chunk_id}")
async def chunk_related(chunk_id: str, current_user=Depends(get_current_user)):
    """Return entities + intra-chunk relations for a chunk.

    Response shape::

        {"chunk_id": "...",
         "entities": [{"entity_id", "name", "type", "relations": [...]}, ...]}

    Used by SourceCard's "relations" popover to show *which* entities the
    cited chunk discusses, so the user can navigate from a chunk to the
    graph view centered on a specific entity.
    """
    store = _open_store_or_none()
    if store is None:
        raise HTTPException(status_code=503, detail="Graph layer disabled or unreachable")

    try:
        rows = await store.chunk_graph(chunk_id)
    except GraphStoreError as exc:
        logger.warning("chunk_graph_failed", chunk_id=chunk_id, error=str(exc))
        raise HTTPException(status_code=503, detail=f"Graph query failed: {exc}") from exc

    return {
        "chunk_id": chunk_id,
        "entities": [
            {
                "entity_id": r["entity_id"],
                "name": r["name"],
                "type": r.get("type"),
                "relations": [rel for rel in (r.get("relations") or []) if rel and rel.get("target")],
            }
            for r in rows
        ],
    }


class RebuildRequest(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=100000, description="Max articles to re-process")
    from_milvus: bool = Field(default=True, description="Re-extract from Milvus rather than re-collect")


@router.post("/rebuild", response_model=GraphRebuildResponse)
async def graph_rebuild(
    body: RebuildRequest | None = None,
    current_user=Depends(get_current_user),
):
    """Async-trigger a graph rebuild (re-extract entities/relations).

    Returns immediately with a task_id; progress is visible via the
    /api/ingest/task/{task_id} endpoint (the rebuild piggybacks on the
    ingest task model so we don't need a separate task table yet).
    """
    if not getattr(settings, "graph_enabled", True):
        return GraphRebuildResponse(
            status="skipped",
            message="Graph layer is disabled (GRAPH_ENABLED=false)",
        )

    payload = body or RebuildRequest()
    task_id = f"graph_rebuild_{uuid.uuid4().hex[:12]}"

    async def _run() -> None:
        try:
            from scripts.build_graph import (
                build_from_milvus,
            )  # late import; CLI script may not be on path
        except ImportError as exc:
            logger.error("graph_rebuild_import_failed", error=str(exc))
            return
        try:
            await build_from_milvus(limit=payload.limit)
            logger.info("graph_rebuild_completed", task_id=task_id, limit=payload.limit)
        except Exception as exc:  # noqa: BLE001
            logger.error("graph_rebuild_failed", task_id=task_id, error=str(exc))

    # We don't persist this task in IngestTask because the schema doesn't
    # fit perfectly (no articles_collected, no source). For now the task
    # is fire-and-forget; users see results in the graph_stats endpoint.
    asyncio.create_task(_run())

    return GraphRebuildResponse(
        status="started",
        message=f"Graph rebuild enqueued (limit={payload.limit}, from_milvus={payload.from_milvus})",
        task_id=task_id,
    )
