"""Tests for the MCP internal bridge. No Milvus or LLM."""

import asyncio

import pytest

from src.mcpbridge.service import (
    ClientDisconnected,
    MCPBridge,
    assert_public_http_url,
    run_cancellable,
)


def _row(company_id, chunk_id="c1", score=0.4, **extra):
    row = {
        "company_id": company_id,
        "chunk_id": chunk_id,
        "parent_doc_id": extra.pop("parent_doc_id", "doc-1"),
        "title": extra.pop("title", "Filing"),
        "content": extra.pop("content", "标题：Filing\n\nbody text"),
        "source": extra.pop("source", "sec"),
        "published_at": extra.pop("published_at", 1_700_000_000),
        "score": score,
        "id": extra.pop("id", 7),
    }
    row.update(extra)
    return row


class _Disconnected:
    def __init__(self, after):
        self.after = after
        self.calls = 0

    async def is_disconnected(self):
        self.calls += 1
        return self.calls > self.after


def test_shared_corpus_filter_is_explicit_empty_company():
    from retrieval.retriever import build_filter_expr

    assert build_filter_expr({"company_id": ""}) == 'company_id == ""'
    assert build_filter_expr({"company_id": "acme"}) == 'company_id == "acme"'


class TestRewriteAndSearch:
    async def test_analyze_failure_falls_back_to_original_query(self):
        seen = []

        async def analyze(state):
            raise RuntimeError("llm unavailable")

        async def retrieve(query, top_k, filters, strategy):
            seen.append((query, filters["company_id"], strategy))
            return [_row("acme", score=0.2, boosted_score=0.9)]

        bridge = MCPBridge(retrieve=retrieve, analyze=analyze, shared_corpus=False)
        rewritten = await bridge.rewrite("what did they spend?", context="3M capex")
        assert rewritten["rewrite_fallback"] is True
        assert rewritten["queries"] == ["what did they spend?"]

        found = await bridge.search(
            queries=rewritten["queries"],
            top_k=5,
            filters={"company_id": "other", "user_id": "nope", "language": "en"},
            tenant_id="acme",
            strategy=rewritten["strategy"],
        )
        assert seen == [("what did they spend?", "acme", "hybrid")]
        assert found["results"][0]["doc_id"] == "doc-1"
        assert found["results"][0]["source"] == "sec"
        assert found["results"][0]["score"] == 0.9
        assert found["results"][0]["timestamp"].startswith("2023-11-14")

    async def test_subqueries_are_searched_and_other_tenants_dropped(self):
        async def analyze(state):
            return {
                "parsed_query": {
                    "intent": "comparison",
                    "rewritten_query": "3M FY2018 capital expenditure",
                    "sub_queries": ["3M cash flow statement 2018"],
                    "keywords": ["3M", "capex"],
                    "retrieval_strategy": "hybrid",
                },
                "search_strategy": "hybrid",
            }

        async def retrieve(query, top_k, filters, strategy):
            return [
                _row("acme", chunk_id="a", score=0.2),
                _row("rival", chunk_id="b", score=0.99),
                _row("acme", chunk_id="a", score=0.1),
            ]

        bridge = MCPBridge(retrieve=retrieve, analyze=analyze)
        rewritten = await bridge.rewrite("how much did they spend on capex?")
        assert rewritten["rewrite_applied"] is True
        assert rewritten["queries"][0] == "3M FY2018 capital expenditure"
        found = await bridge.search(
            queries=rewritten["queries"],
            top_k=5,
            filters=None,
            tenant_id="acme",
            strategy=rewritten["strategy"],
        )
        assert [item["chunk_id"] for item in found["results"]] == ["a"]

    async def test_shared_corpus_reads_unscoped_rows_only(self):
        calls = []

        async def retrieve(query, top_k, filters, strategy):
            calls.append(filters["company_id"])
            return [
                _row("", chunk_id="shared", parent_doc_id="shared-doc", score=0.5),
                _row("someone-else", chunk_id="secret", score=0.8),
            ]

        bridge = MCPBridge(retrieve=retrieve, shared_corpus=True)
        found = await bridge.search(
            queries=["3M"],
            top_k=5,
            filters=None,
            tenant_id="acme",
            strategy="vector",
        )
        assert calls == ["acme", ""]
        assert [item["chunk_id"] for item in found["results"]] == ["shared"]


class TestIngestAndDocument:
    async def test_ingest_scopes_chunks_to_tenant(self):
        indexed = {}

        async def index(articles, company_id):
            indexed["articles"] = articles
            indexed["company_id"] = company_id
            return {"chunks": 2, "inserted": 2}

        bridge = MCPBridge(index=index)
        result = await bridge.ingest(tenant_id="acme", text="Revenue was $10.\n\nCosts were $4.")
        assert indexed["company_id"] == "acme"
        assert indexed["articles"][0]["parent_doc_id"] == result["doc_id"]
        assert result["chunks"] == 2
        assert result["inserted"] == 2

    async def test_ingest_rejects_both_text_and_url(self):
        bridge = MCPBridge()
        with pytest.raises(ValueError):
            await bridge.ingest(tenant_id="acme", text="hello", url="https://example.com")

    async def test_get_document_hides_other_tenants_and_joins_chunks(self):
        stored = {
            'parent_doc_id == "doc-1" and company_id == "acme"': [
                _row("acme", chunk_id="doc-1:1", content="标题：Filing\n\nsecond"),
                _row("acme", chunk_id="doc-1:0", content="标题：Filing\n\nfirst"),
            ],
            'parent_doc_id == "doc-1" and company_id == "other"': [
                _row("other", chunk_id="doc-1:0", content="secret"),
            ],
        }

        async def query_store(expr, limit=100):
            if 'parent_doc_id == "doc-1"' in expr and 'company_id == "acme"' in expr:
                if expr.startswith("(parent_doc_id"):
                    return stored['parent_doc_id == "doc-1" and company_id == "acme"'][:1]
                return stored['parent_doc_id == "doc-1" and company_id == "acme"']
            if 'company_id == "other"' in expr:
                return stored['parent_doc_id == "doc-1" and company_id == "other"']
            return []

        bridge = MCPBridge(query_store=query_store, shared_corpus=False)
        document = await bridge.get_document("doc-1", tenant_id="acme")
        assert document["text"] == "first\n\nsecond"
        assert document["source"] == "sec"
        assert document["doc_id"] == "doc-1"
        missing = await bridge.get_document("doc-1", tenant_id="other-tenant")
        assert missing is None

    def test_public_url_guard_rejects_loopback_and_private(self):
        with pytest.raises(ValueError):
            assert_public_http_url("http://127.0.0.1/secret")
        with pytest.raises(ValueError):
            assert_public_http_url("http://10.1.2.3/secret")
        with pytest.raises(ValueError):
            assert_public_http_url("file:///etc/passwd")


class TestCancellation:
    async def test_disconnect_cancels_work(self):
        started = asyncio.Event()

        async def slow():
            started.set()
            await asyncio.sleep(30)

        request = _Disconnected(after=0)
        with pytest.raises(ClientDisconnected):
            await run_cancellable(request, slow())


class TestHTTP:
    def test_disabled_without_token(self, client):
        response = client.post(
            "/api/internal/mcp/search",
            json={"queries": ["hello"]},
        )
        assert response.status_code == 503

    def test_rejects_bad_token_and_serves_tenant_from_header(self, client):
        from core.config import settings

        previous = settings.mcp_internal_token
        settings.mcp_internal_token = "internal-test-token"
        seen = {}

        class FakeBridge:
            async def search(self, **kwargs):
                seen.update(kwargs)
                return {"queries": kwargs["queries"], "strategy": "hybrid", "top_k": 5, "results": []}

            async def rewrite(self, **kwargs):
                return {}

            async def ingest(self, **kwargs):
                return {}

            async def get_document(self, **kwargs):
                return None

        from src.api import mcp_internal

        client.app.dependency_overrides[mcp_internal.get_bridge] = lambda: FakeBridge()
        try:
            denied = client.post(
                "/api/internal/mcp/search",
                json={"queries": ["hello"]},
                headers={"Authorization": "Bearer wrong"},
            )
            assert denied.status_code == 401

            ok = client.post(
                "/api/internal/mcp/search",
                json={"queries": ["hello"], "filters": {"company_id": "injected"}},
                headers={
                    "Authorization": "Bearer internal-test-token",
                    "X-Tenant-ID": "acme",
                },
            )
            assert ok.status_code == 200
            assert seen["tenant_id"] == "acme"
            assert seen["filters"]["company_id"] == "injected"
        finally:
            settings.mcp_internal_token = previous
            client.app.dependency_overrides.clear()
