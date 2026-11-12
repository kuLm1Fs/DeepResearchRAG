"""Retrieval and ingest operations exposed to the MCP server.

The Go process owns the MCP protocol. This module reuses the Python
retrieval core (multi-path recall, RRF, time decay, source-quality
weighting, cross-encoder rerank) and the existing ``analyze_query``
node for optional rewriting.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

from core import get_logger, settings

logger = get_logger(__name__)

MAX_INGEST_CHARS = 400_000
MAX_QUERIES = 8
MAX_QUERY_CHARS = 1000
_ALLOWED_STRATEGIES = {"hybrid", "vector", "graph"}
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


class ClientDisconnected(Exception):
    """The caller closed the HTTP request before the work finished."""


class MCPBridge:
    def __init__(
        self,
        retrieve: Callable[..., Awaitable[list[dict[str, Any]]]] | None = None,
        analyze: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]] | None = None,
        index: Callable[..., Awaitable[dict[str, Any]]] | None = None,
        query_store: Callable[..., Awaitable[list[dict[str, Any]]]] | None = None,
        fetch_url: Callable[[str], Awaitable[tuple[str, str]]] | None = None,
        shared_corpus: bool | None = None,
    ):
        self.retrieve = retrieve or _default_retrieve
        self.analyze = analyze or _default_analyze
        self.index = index or _default_index
        self.query_store = query_store or _default_query_store
        self.fetch_url = fetch_url or fetch_public_url
        self.shared_corpus = settings.mcp_shared_corpus if shared_corpus is None else shared_corpus

    async def rewrite(
        self,
        query: str,
        context: str | None = None,
        trace_id: str = "",
    ) -> dict[str, Any]:
        """Run analyze_query. On any failure, return the original query."""
        query = _clean_query(query)
        try:
            state: dict[str, Any] = {"query": query}
            if context and context.strip():
                state["use_history"] = True
                state["conversation_history"] = [
                    {"role": "user", "content": context.strip()[:4000]}
                ]
            analyzed = await self.analyze(state)
        except Exception as exc:
            logger.warning("mcp_rewrite_failed", trace_id=trace_id, error=str(exc))
            return _original_rewrite(query, str(exc))

        parsed = analyzed.get("parsed_query") or {}
        rewritten = str(parsed.get("rewritten_query") or query).strip() or query
        sub_queries = []
        for item in parsed.get("sub_queries") or []:
            if isinstance(item, str) and item.strip():
                sub_queries.append(item.strip()[:MAX_QUERY_CHARS])
        queries = [rewritten[:MAX_QUERY_CHARS], *sub_queries][:MAX_QUERIES]
        strategy = str(
            analyzed.get("search_strategy")
            or parsed.get("retrieval_strategy")
            or "hybrid"
        )
        if strategy not in _ALLOWED_STRATEGIES:
            strategy = "hybrid"
        changed = queries != [query]
        return {
            "queries": queries,
            "strategy": strategy,
            "intent": parsed.get("intent") or "factual",
            "keywords": [str(k) for k in (parsed.get("keywords") or []) if isinstance(k, str)],
            "rewrite_applied": changed,
            "rewrite_fallback": False,
            "rewrite_error": "",
        }

    async def search(
        self,
        queries: list[str],
        top_k: int,
        filters: dict[str, Any] | None,
        tenant_id: str,
        strategy: str = "hybrid",
        trace_id: str = "",
    ) -> dict[str, Any]:
        cleaned = []
        for query in queries:
            text = _clean_query(query) if isinstance(query, str) else ""
            if text:
                cleaned.append(text)
        if not cleaned:
            raise ValueError("at least one query is required")
        cleaned = cleaned[:MAX_QUERIES]
        top_k = _clamp_top_k(top_k)
        if strategy not in _ALLOWED_STRATEGIES:
            strategy = "hybrid"

        scopes = [tenant_id]
        if self.shared_corpus:
            scopes.append("")

        seen: set[str] = set()
        merged: list[dict[str, Any]] = []
        per_query = max(top_k, 3)
        for scope in scopes:
            scoped_filters = _public_filters(filters)
            scoped_filters["company_id"] = scope
            for query in cleaned:
                rows = await self._retrieve(query, per_query, scoped_filters, strategy)
                for row in rows:
                    if not _row_visible(row, tenant_id, self.shared_corpus):
                        continue
                    key = str(
                        row.get("chunk_id")
                        or row.get("content_hash")
                        or row.get("id")
                        or ""
                    )
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    merged.append(row)

        merged.sort(key=_rank_score, reverse=True)
        results = [_evidence(row) for row in merged[:top_k]]
        logger.info(
            "mcp_search_completed",
            trace_id=trace_id,
            tenant_id=tenant_id,
            queries=len(cleaned),
            returned=len(results),
        )
        return {
            "queries": cleaned,
            "strategy": strategy,
            "top_k": top_k,
            "results": results,
        }

    async def ingest(
        self,
        tenant_id: str,
        text: str | None = None,
        url: str | None = None,
        title: str | None = None,
        source: str | None = None,
        language: str | None = None,
        category: str | None = None,
        trace_id: str = "",
    ) -> dict[str, Any]:
        provided = [bool(text and text.strip()), bool(url and url.strip())]
        if sum(provided) != 1:
            raise ValueError("provide exactly one of text or url")

        truncated = False
        resolved_title = (title or "").strip()
        body = ""
        resolved_url = ""
        if url and url.strip():
            resolved_url = url.strip()
            fetched_title, body = await self.fetch_url(resolved_url)
            if not resolved_title:
                resolved_title = fetched_title
        else:
            body = text or ""

        body = body.replace("\x00", "").strip()
        if not body:
            raise ValueError("document text is empty")
        if len(body) > MAX_INGEST_CHARS:
            body = body[:MAX_INGEST_CHARS]
            truncated = True
        if not resolved_title:
            first = body.splitlines()[0].strip() if body.splitlines() else "untitled"
            resolved_title = first[:180] or "untitled"
        resolved_title = resolved_title[:200]
        doc_id = str(uuid.uuid4())
        now = int(time.time())
        article = {
            "title": resolved_title,
            "content": body,
            "source": (source or "mcp").strip()[:64] or "mcp",
            "language": (language or "").strip()[:10],
            "category": (category or "document").strip()[:32] or "document",
            "url": resolved_url[:2048],
            "published_at": now,
            "pub_time": datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%d"),
            "parent_doc_id": doc_id,
            "external_id": doc_id,
        }
        stats = await self.index([article], company_id=tenant_id)
        logger.info(
            "mcp_ingest_completed",
            trace_id=trace_id,
            tenant_id=tenant_id,
            doc_id=doc_id,
            chunks=stats.get("chunks", 0),
            inserted=stats.get("inserted", 0),
        )
        return {
            "doc_id": doc_id,
            "title": resolved_title,
            "source": article["source"],
            "url": resolved_url,
            "chunks": int(stats.get("chunks", 0)),
            "inserted": int(stats.get("inserted", 0)),
            "truncated": truncated,
        }

    async def get_document(
        self,
        doc_id: str,
        tenant_id: str,
        trace_id: str = "",
    ) -> dict[str, Any] | None:
        doc_id = (doc_id or "").strip()
        if not doc_id or len(doc_id) > 128:
            raise ValueError("doc_id is required and must be at most 128 characters")

        anchor = await self._find_anchor(doc_id, tenant_id)
        if anchor is None and self.shared_corpus:
            anchor = await self._find_anchor(doc_id, "")
        if anchor is None:
            return None

        parent = str(anchor.get("parent_doc_id") or doc_id)
        owner = str(anchor.get("company_id") or "")
        if owner != tenant_id and not (self.shared_corpus and owner == ""):
            return None
        rows = await self.query_store(
            expr=_doc_expr(parent, owner),
            limit=500,
        )
        visible = [row for row in rows if _row_visible(row, tenant_id, self.shared_corpus)]
        if not visible:
            visible = [anchor]
        visible.sort(key=lambda row: _chunk_index(str(row.get("chunk_id") or "")))
        parts = []
        for row in visible:
            body = _chunk_body(str(row.get("content") or ""))
            if body:
                parts.append(body)
        head = visible[0]
        published = head.get("published_at") or 0
        logger.info(
            "mcp_get_document_completed",
            trace_id=trace_id,
            tenant_id=tenant_id,
            doc_id=parent,
            chunks=len(visible),
        )
        return {
            "doc_id": parent,
            "title": head.get("title") or "",
            "source": head.get("source") or "",
            "url": head.get("url") or "",
            "timestamp": _timestamp(published),
            "published_at": int(published or 0),
            "text": "\n\n".join(parts),
            "chunks": [
                {
                    "chunk_id": row.get("chunk_id") or "",
                    "content": row.get("content") or "",
                }
                for row in visible
            ],
        }

    async def _retrieve(self, query, top_k, filters, strategy) -> list[dict[str, Any]]:
        try:
            return await self.retrieve(query, top_k=top_k, filters=filters, strategy=strategy)
        except TypeError:
            return await self.retrieve(query, top_k=top_k, filters=filters)

    async def _find_anchor(self, doc_id: str, company_id: str) -> dict[str, Any] | None:
        rows = await self.query_store(expr=_lookup_expr(doc_id, company_id), limit=5)
        for row in rows:
            if str(row.get("company_id") or "") != company_id:
                continue
            return row
        return None


def _original_rewrite(query: str, error: str) -> dict[str, Any]:
    return {
        "queries": [query],
        "strategy": "hybrid",
        "intent": "factual",
        "keywords": [],
        "rewrite_applied": False,
        "rewrite_fallback": True,
        "rewrite_error": error[:300],
    }


def _clean_query(query: str) -> str:
    return " ".join((query or "").split())[:MAX_QUERY_CHARS]


def _clamp_top_k(top_k: int) -> int:
    try:
        value = int(top_k)
    except (TypeError, ValueError):
        value = 5
    return max(1, min(value, 50))


def _public_filters(filters: dict[str, Any] | None) -> dict[str, Any]:
    """Keep caller filters that the retriever already understands.

    company_id and user_id are never taken from the caller. The bridge
    sets company_id from the authenticated tenant.
    """
    allowed = {"language", "category", "source", "published_at_from", "published_at_to"}
    cleaned: dict[str, Any] = {}
    for key, value in (filters or {}).items():
        if key not in allowed or value is None or value == "":
            continue
        if key in {"published_at_from", "published_at_to"}:
            cleaned[key] = int(value)
        else:
            cleaned[key] = str(value)[:64]
    return cleaned


def _row_visible(row: dict[str, Any], tenant_id: str, shared_corpus: bool) -> bool:
    owner = str(row.get("company_id") or "")
    if owner == tenant_id:
        return True
    return shared_corpus and owner == ""


def _rank_score(row: dict[str, Any]) -> float:
    for key in ("boosted_score", "fused_score", "score"):
        value = row.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def _evidence(row: dict[str, Any]) -> dict[str, Any]:
    published = row.get("published_at") or 0
    doc_id = str(row.get("parent_doc_id") or row.get("chunk_id") or row.get("id") or "")
    return {
        "doc_id": doc_id,
        "chunk_id": str(row.get("chunk_id") or ""),
        "id": str(row.get("id") or ""),
        "title": row.get("title") or "",
        "content": row.get("content") or "",
        "source": row.get("source") or "",
        "url": row.get("url") or "",
        "timestamp": _timestamp(published),
        "published_at": int(published or 0),
        "score": _rank_score(row),
        "language": row.get("language") or "",
        "category": row.get("category") or "",
    }


def _timestamp(published: Any) -> str | None:
    try:
        value = int(published or 0)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


def _chunk_index(chunk_id: str) -> int:
    tail = chunk_id.rsplit(":", 1)[-1] if chunk_id else ""
    try:
        return int(tail)
    except ValueError:
        return 0


def _chunk_body(content: str) -> str:
    if content.startswith("标题："):
        head, sep, body = content.partition("\n\n")
        if sep:
            return body.strip()
    return content.strip()


def _escape(value: str) -> str:
    from retrieval.retriever import escape_milvus_string_value

    return escape_milvus_string_value(value)


def _lookup_expr(doc_id: str, company_id: str) -> str:
    escaped = _escape(doc_id)
    clauses = [f'parent_doc_id == "{escaped}"', f'chunk_id == "{escaped}"']
    if doc_id.isdigit():
        clauses.append(f"id == {int(doc_id)}")
    identity = "(" + " or ".join(clauses) + ")"
    return f'{identity} and company_id == "{_escape(company_id)}"'


def _doc_expr(parent_doc_id: str, company_id: str) -> str:
    return (
        f'parent_doc_id == "{_escape(parent_doc_id)}" '
        f'and company_id == "{_escape(company_id)}"'
    )


async def run_cancellable(request, awaitable: Awaitable[Any]) -> Any:
    """Await work until it finishes or the HTTP client disconnects."""
    task = asyncio.ensure_future(awaitable)
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=0.25)
            if task in done:
                return task.result()
            if await request.is_disconnected():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                raise ClientDisconnected()
    except asyncio.CancelledError:
        task.cancel()
        raise


def assert_public_http_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("only http and https URLs are allowed")
    if parsed.username or parsed.password:
        raise ValueError("URLs with credentials are not allowed")
    host = parsed.hostname
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ValueError(f"could not resolve host: {host}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise ValueError("refusing non-public URL")


async def fetch_public_url(url: str) -> tuple[str, str]:
    """Fetch a public URL and return (title, text). Redirects are re-checked."""
    import httpx

    assert_public_http_url(url)
    current = url
    async with httpx.AsyncClient(
        timeout=20,
        follow_redirects=False,
        headers={"User-Agent": "rag-mcp/1.0"},
    ) as client:
        for _ in range(3):
            assert_public_http_url(current)
            response = await client.get(current)
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise ValueError("redirect missing location")
                current = urljoin(current, location)
                continue
            response.raise_for_status()
            raw = response.content[:8_000_000]
            html = raw.decode(response.encoding or "utf-8", errors="replace")
            title_match = _TITLE_RE.search(html)
            title = _SPACE_RE.sub(" ", title_match.group(1)).strip() if title_match else ""
            text = ""
            try:
                import trafilatura

                extracted = trafilatura.extract(html, url=current, include_comments=False)
                text = extracted or ""
            except Exception as exc:
                logger.warning("mcp_trafilatura_failed", url=current, error=str(exc))
            if not text.strip():
                text = _SPACE_RE.sub(" ", _TAG_RE.sub(" ", html))
            return title[:200], text.strip()
    raise ValueError("too many redirects")


async def _default_analyze(state: dict[str, Any]) -> dict[str, Any]:
    from agent.nodes import analyze_query

    return await analyze_query(state)


async def _default_retrieve(query: str, top_k: int = 5, filters=None, strategy: str = "hybrid"):
    from agent.runtime import AgentRuntime

    retriever = AgentRuntime().create_retriever()
    return await retriever.retrieve(query, top_k=top_k, filters=filters, strategy=strategy)


async def _default_index(articles: list[dict[str, Any]], company_id: str) -> dict[str, Any]:
    from ingestion.indexer import index_articles

    return await index_articles(
        articles,
        user_id="",
        company_id=company_id,
        build_graph=False,
    )


async def _default_query_store(expr: str, limit: int = 100) -> list[dict[str, Any]]:
    from vectorstore import MilvusStore

    store = MilvusStore()
    return await store.query_async(
        expr=expr,
        output_fields=[
            "title",
            "content",
            "source",
            "language",
            "category",
            "published_at",
            "content_hash",
            "url",
            "chunk_id",
            "parent_doc_id",
            "user_id",
            "company_id",
            "id",
        ],
        limit=limit,
    )
