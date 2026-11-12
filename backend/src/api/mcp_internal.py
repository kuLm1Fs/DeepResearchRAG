"""HTTP bridge for the rag-mcp server.

These routes are not for browsers. The Go server authenticates MCP
clients, maps a bearer token to a tenant, and calls here with the
shared internal token plus that tenant id.
"""

from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from core import get_logger, settings
from mcpbridge.service import ClientDisconnected, MCPBridge, run_cancellable

from .app import limiter

logger = get_logger(__name__)
router = APIRouter(prefix="/internal/mcp", tags=["mcp-internal"])

_bridge: MCPBridge | None = None


def get_bridge() -> MCPBridge:
    global _bridge
    if _bridge is None:
        _bridge = MCPBridge()
    return _bridge


class RewriteRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    context: str | None = Field(default=None, max_length=4000)


class SearchRequest(BaseModel):
    queries: list[str] = Field(..., min_length=1, max_length=8)
    top_k: int = Field(default=5, ge=1, le=50)
    filters: dict[str, Any] | None = None
    strategy: str = Field(default="hybrid")


class IngestRequest(BaseModel):
    text: str | None = None
    url: str | None = None
    title: str | None = Field(default=None, max_length=200)
    source: str | None = Field(default=None, max_length=64)
    language: str | None = Field(default=None, max_length=10)
    category: str | None = Field(default=None, max_length=32)


def require_internal_caller(request: Request) -> str:
    """Return the tenant id after checking the shared internal token."""
    expected = settings.mcp_internal_token
    if not expected:
        raise HTTPException(status_code=503, detail="MCP internal API is disabled")
    presented = _bearer(request.headers.get("authorization", ""))
    if not presented:
        presented = request.headers.get("x-internal-token", "")
    if not presented or not hmac.compare_digest(presented, expected):
        raise HTTPException(status_code=401, detail="invalid internal token")
    tenant = (request.headers.get("x-tenant-id") or "").strip()
    if not tenant or len(tenant) > 64 or any(ch.isspace() for ch in tenant):
        raise HTTPException(status_code=400, detail="invalid tenant id")
    return tenant


def _bearer(header: str) -> str:
    prefix = "bearer "
    if header.lower().startswith(prefix):
        return header[len(prefix):].strip()
    return ""


def _trace_id(request: Request) -> str:
    return getattr(request.state, "trace_id", "") or request.headers.get("x-trace-id", "")


@router.post("/rewrite")
@limiter.limit("2000/minute")
async def rewrite_query(
    body: RewriteRequest,
    request: Request,
    bridge: MCPBridge = Depends(get_bridge),
):
    tenant = require_internal_caller(request)
    trace_id = _trace_id(request)
    logger.info("mcp_rewrite_request", trace_id=trace_id, tenant_id=tenant)
    try:
        return await run_cancellable(
            request,
            bridge.rewrite(body.query, context=body.context, trace_id=trace_id),
        )
    except ClientDisconnected as exc:
        raise HTTPException(status_code=499, detail="client cancelled") from exc


@router.post("/search")
@limiter.limit("2000/minute")
async def search_documents(
    body: SearchRequest,
    request: Request,
    bridge: MCPBridge = Depends(get_bridge),
):
    tenant = require_internal_caller(request)
    trace_id = _trace_id(request)
    logger.info("mcp_search_request", trace_id=trace_id, tenant_id=tenant, top_k=body.top_k)
    try:
        return await run_cancellable(
            request,
            bridge.search(
                queries=body.queries,
                top_k=body.top_k,
                filters=body.filters,
                tenant_id=tenant,
                strategy=body.strategy,
                trace_id=trace_id,
            ),
        )
    except ClientDisconnected as exc:
        raise HTTPException(status_code=499, detail="client cancelled") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("mcp_search_failed", trace_id=trace_id, tenant_id=tenant, error=str(exc))
        raise HTTPException(status_code=503, detail="retrieval failed") from exc


@router.post("/ingest")
@limiter.limit("2000/minute")
async def ingest_document(
    body: IngestRequest,
    request: Request,
    bridge: MCPBridge = Depends(get_bridge),
):
    tenant = require_internal_caller(request)
    trace_id = _trace_id(request)
    logger.info("mcp_ingest_request", trace_id=trace_id, tenant_id=tenant)
    try:
        return await run_cancellable(
            request,
            bridge.ingest(
                tenant_id=tenant,
                text=body.text,
                url=body.url,
                title=body.title,
                source=body.source,
                language=body.language,
                category=body.category,
                trace_id=trace_id,
            ),
        )
    except ClientDisconnected as exc:
        raise HTTPException(status_code=499, detail="client cancelled") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("mcp_ingest_failed", trace_id=trace_id, tenant_id=tenant, error=str(exc))
        raise HTTPException(status_code=503, detail="ingest failed") from exc


@router.get("/documents/{doc_id}")
@limiter.limit("2000/minute")
async def get_document(
    doc_id: str,
    request: Request,
    bridge: MCPBridge = Depends(get_bridge),
):
    tenant = require_internal_caller(request)
    trace_id = _trace_id(request)
    try:
        document = await run_cancellable(
            request,
            bridge.get_document(doc_id, tenant_id=tenant, trace_id=trace_id),
        )
    except ClientDisconnected as exc:
        raise HTTPException(status_code=499, detail="client cancelled") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("mcp_get_document_failed", trace_id=trace_id, tenant_id=tenant, error=str(exc))
        raise HTTPException(status_code=503, detail="document lookup failed") from exc
    if document is None:
        raise HTTPException(status_code=404, detail="document not found")
    return document
