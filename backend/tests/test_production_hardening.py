import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.config import Settings
from core.errors import EmbeddingError
from src.agent import graph as agent_graph
from src.agent import nodes
from src.agent.runtime import AgentRuntime
from src.api import auth as auth_api
from src.llm.cache import CachedLLM
from src.retrieval.retriever import MultiPathRetriever, build_like_expr, escape_milvus_like_value
from src.vectorstore import embedding


class ProductionSettingsTests(unittest.TestCase):
    def test_prod_effective_flags_disable_debug_and_cache(self):
        settings = Settings(env="prod", debug=True, llm_cache=True)

        self.assertTrue(settings.is_prod)
        self.assertFalse(settings.debug_enabled)
        self.assertFalse(settings.llm_cache_enabled)

    def test_agent_runtime_uses_effective_cache_flag(self):
        llm = object()
        settings = Settings(env="prod", llm_cache=True)

        wrapped = AgentRuntime(config=settings).with_answer_cache(llm)

        self.assertIs(wrapped, llm)
        self.assertNotIsInstance(wrapped, CachedLLM)


class RefreshTokenHardeningTests(unittest.TestCase):
    def test_select_valid_refresh_token_requires_exact_token_hash(self):
        class Token:
            def __init__(self, token_hash, expires_at, revoked=False):
                self.token_hash = token_hash
                self.expires_at = expires_at
                self.revoked = revoked

        requested_token = "refresh-token-from-client"
        matching = Token(
            token_hash=auth_api.hash_token(requested_token),
            expires_at=datetime.utcnow() + timedelta(days=1),
        )
        latest_but_wrong = Token(
            token_hash=auth_api.hash_token("different-refresh-token"),
            expires_at=datetime.utcnow() + timedelta(days=1),
        )

        selected = auth_api.select_valid_refresh_token(
            requested_token,
            [latest_but_wrong, matching],
            now=datetime.utcnow(),
        )

        self.assertIs(selected, matching)

    def test_select_valid_refresh_token_rejects_expired_or_revoked_tokens(self):
        class Token:
            def __init__(self, token_hash, expires_at, revoked=False):
                self.token_hash = token_hash
                self.expires_at = expires_at
                self.revoked = revoked

        requested_token = "refresh-token-from-client"
        now = datetime.utcnow()
        tokens = [
            Token(auth_api.hash_token(requested_token), now + timedelta(days=1), revoked=True),
            Token(auth_api.hash_token(requested_token), now - timedelta(seconds=1), revoked=False),
        ]

        self.assertIsNone(auth_api.select_valid_refresh_token(requested_token, tokens, now=now))


class MilvusExpressionHardeningTests(unittest.TestCase):
    def test_escape_milvus_like_value_escapes_user_controlled_syntax(self):
        escaped = escape_milvus_like_value('AI "agent" \\ 100%_news')

        self.assertEqual(escaped, 'AI \\"agent\\" \\\\ 100\\%\\_news')

    def test_build_like_expr_uses_escaped_value_for_each_field(self):
        expr = build_like_expr(["title", "content"], 'AI "agent"')

        self.assertEqual(expr, 'title like "%AI \\"agent\\"%" or content like "%AI \\"agent\\"%"')


class RetrieverFilterPushdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_retriever_pushes_filters_into_milvus_queries(self):
        class FakeStore:
            def __init__(self):
                self.search_expr = None
                self.query_exprs = []

            def search(self, query_embedding, top_k, expr=None):
                self.search_expr = expr
                return []

            def query(self, expr, output_fields=None, limit=100):
                self.query_exprs.append(expr)
                return []

        fake_store = FakeStore()
        retriever = MultiPathRetriever(fake_store, rerank_enabled=False)

        with patch("src.retrieval.retriever.embed_texts_async", return_value=[[0.1] * 1024]):
            await retriever.retrieve(
                "AI",
                filters={"company_id": "comp_123", "user_id": "user_456", "language": "zh"},
            )

        self.assertEqual(
            fake_store.search_expr,
            'company_id == "comp_123" and user_id == "user_456" and language == "zh"',
        )
        self.assertEqual(
            fake_store.query_exprs,
            [
                '(title like "%AI%" or content like "%AI%") and company_id == "comp_123" and user_id == "user_456" and language == "zh"',
                '(title like "%AI%") and company_id == "comp_123" and user_id == "user_456" and language == "zh"',
            ],
        )


class EmbeddingFailureHardeningTests(unittest.IsolatedAsyncioTestCase):
    async def test_embed_texts_async_raises_instead_of_returning_zero_vectors(self):
        async def fail_call(texts):
            raise RuntimeError("provider unavailable")

        with patch.object(embedding, "_call_embedding_api", side_effect=fail_call):
            with self.assertRaises(EmbeddingError):
                await embedding.embed_texts_async(["hello"])


class TenantIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_agent_retrieve_passes_tenant_filters_to_retriever(self):
        class FakeRetriever:
            def __init__(self):
                self.filters = None

            async def retrieve(self, query, top_k, filters=None):
                self.filters = filters
                return [{"title": "Tenant result", "content": "evidence", "score": 0.9}]

        fake_retriever = FakeRetriever()
        runtime = type("Runtime", (), {
            "create_retriever": lambda self: fake_retriever,
        })()

        result = await nodes.retrieve({
            "runtime": runtime,
            "search_plan": {"queries": ["tenant query"], "per_query": 1, "total": 1},
            "filters": {"company_id": "comp_123"},
            "top_k": 1,
        })

        self.assertEqual(fake_retriever.filters, {"company_id": "comp_123"})
        self.assertEqual(result["retrieval_results"][0]["title"], "Tenant result")

    async def test_agent_re_search_passes_tenant_filters_to_retriever(self):
        class FakeRetriever:
            def __init__(self):
                self.filters = None

            async def retrieve(self, query, top_k, filters=None):
                self.filters = filters
                return [{"title": "Tenant follow-up", "content": "more evidence", "score": 0.8}]

        fake_retriever = FakeRetriever()
        runtime = type("Runtime", (), {
            "create_retriever": lambda self: fake_retriever,
        })()

        result = await nodes.re_search({
            "runtime": runtime,
            "retrieval_evaluation": {"re_search_query": "tenant follow-up"},
            "retrieval_results": [],
            "filters": {"company_id": "comp_123", "user_id": "user_456"},
            "top_k": 1,
        })

        self.assertEqual(fake_retriever.filters, {"company_id": "comp_123", "user_id": "user_456"})
        self.assertEqual(result["retrieval_results"][0]["title"], "Tenant follow-up")

    def test_initial_state_carries_filters(self):
        state = agent_graph.build_initial_state(
            "tenant query",
            filters={"company_id": "comp_123", "language": "zh"},
        )

        self.assertEqual(state["filters"], {"company_id": "comp_123", "language": "zh"})
