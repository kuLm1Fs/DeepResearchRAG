"""Tests for the GraphRAG query routing rules (Phase 4).

The router lives in ``src.agent.nodes.apply_routing_rules``. These tests
cover:

  - intent-based routing (summary/analysis/comparison → graph)
  - factual intent + keyword matching a known entity → graph
  - factual intent without entity hit → hybrid
  - caller override (forced_strategy) wins over rules
  - settings.graph_enabled=False forces vector
  - integration with analyze_query node: routing decisions land in
    state["parsed_query"]["retrieval_strategy"]
  - integration with retrieve node: the strategy is forwarded to the
    retriever and (for legacy retrievers without a strategy kwarg) falls
    back gracefully.
"""
import sys
from unittest.mock import AsyncMock, patch

import pytest


def _neo4j_store_patch_target() -> str:
    """Return the dotted path that the runtime will actually look up for
    Neo4jStore. Test ordering can leave only ``src.graph.neo4j_store`` in
    sys.modules; the runtime's import then falls back to that spelling.
    Patching the wrong key is a no-op, so we resolve dynamically."""
    if "graph.neo4j_store" in sys.modules:
        return "graph.neo4j_store.Neo4jStore"
    if "src.graph.neo4j_store" in sys.modules:
        return "src.graph.neo4j_store.Neo4jStore"
    # Neither loaded — force-load the bare spelling so subsequent imports hit it.
    import graph.neo4j_store  # noqa: F401
    return "graph.neo4j_store.Neo4jStore"


# ---------------------------------------------------------------------
# Pure routing rule tests (no LLM, no retriever)
# ---------------------------------------------------------------------


class TestApplyRoutingRules:
    def test_summary_intent_goes_to_graph(self):
        from src.agent.nodes import apply_routing_rules

        result = apply_routing_rules({"intent": "summary", "keywords": []})
        assert result["retrieval_strategy"] == "graph"
        assert "summary" in result["strategy_reason"]

    def test_analysis_intent_goes_to_graph(self):
        from src.agent.nodes import apply_routing_rules

        result = apply_routing_rules({"intent": "analysis", "keywords": []})
        assert result["retrieval_strategy"] == "graph"

    def test_comparison_intent_goes_to_graph(self):
        from src.agent.nodes import apply_routing_rules

        result = apply_routing_rules({"intent": "comparison", "keywords": []})
        assert result["retrieval_strategy"] == "graph"

    def test_factual_with_no_entity_keyword_goes_hybrid(self):
        from src.agent.nodes import apply_routing_rules

        result = apply_routing_rules(
            {"intent": "factual", "keywords": ["what", "is", "etf"]},
            entity_vocabulary={"苹果", "tsmc"},  # no overlap
        )
        assert result["retrieval_strategy"] == "hybrid"
        assert "default" in result["strategy_reason"]

    def test_factual_with_entity_keyword_goes_to_graph(self):
        from src.agent.nodes import apply_routing_rules

        result = apply_routing_rules(
            {"intent": "factual", "keywords": ["苹果", "营收"]},
            entity_vocabulary={"苹果"},
        )
        assert result["retrieval_strategy"] == "graph"
        assert "苹果" in result["strategy_reason"]

    def test_factual_with_entity_keyword_case_insensitive(self):
        from src.agent.nodes import apply_routing_rules

        result = apply_routing_rules(
            {"intent": "factual", "keywords": ["AAPL", "earnings"]},
            entity_vocabulary={"aapl"},  # lowercased
        )
        assert result["retrieval_strategy"] == "graph"

    def test_forced_strategy_wins_over_intent_rules(self):
        from src.agent.nodes import apply_routing_rules

        # Intent says comparison (would normally → graph), but caller forces vector
        result = apply_routing_rules(
            {"intent": "comparison", "keywords": []},
            forced_strategy="vector",
        )
        assert result["retrieval_strategy"] == "vector"
        assert result["strategy_reason"] == "caller_override"

    def test_forced_strategy_rejects_unknown_values(self):
        from src.agent.nodes import apply_routing_rules

        # Junk override is ignored; rules apply normally
        result = apply_routing_rules(
            {"intent": "summary", "keywords": []},
            forced_strategy="not-a-real-strategy",
        )
        assert result["retrieval_strategy"] == "graph"

    def test_graph_disabled_in_settings_forces_vector(self, monkeypatch):
        from src.agent import nodes
        from src.agent.nodes import apply_routing_rules

        monkeypatch.setattr(nodes.settings, "graph_enabled", False)
        result = apply_routing_rules({"intent": "comparison", "keywords": ["foo"]})
        assert result["retrieval_strategy"] == "vector"
        assert "disabled" in result["strategy_reason"]

    def test_missing_intent_treated_as_factual(self):
        from src.agent.nodes import apply_routing_rules

        # No intent key → defaults to factual; no entity hit → hybrid
        result = apply_routing_rules(
            {"keywords": ["whatever"]},
            entity_vocabulary=set(),
        )
        assert result["retrieval_strategy"] == "hybrid"


# ---------------------------------------------------------------------
# analyze_query integration tests
# ---------------------------------------------------------------------


class TestAnalyzeQueryRouting:
    @pytest.mark.asyncio
    async def test_analyze_query_writes_routing_to_parsed_query(self):
        from src.agent import nodes

        class FakeLLM:
            async def chat(self, messages):
                return (
                    '{"intent": "comparison", "rewritten_query": "Apple vs Samsung", '
                    '"sub_queries": [], "keywords": ["Apple", "Samsung"]}'
                )

        with (
            patch("llm.create_llm", return_value=FakeLLM()),
            patch.object(nodes, "load_prompt", return_value="prompt"),
        ):
            result = await nodes.analyze_query({"query": "Apple vs Samsung"})

        assert result["parsed_query"]["retrieval_strategy"] == "graph"
        assert result["parsed_query"]["strategy_reason"] == "intent_is_comparison"
        # search_strategy in top-level state for the API/graph layer
        assert result["search_strategy"] == "graph"

    @pytest.mark.asyncio
    async def test_analyze_query_respects_forced_strategy_in_state(self):
        from src.agent import nodes

        class FakeLLM:
            async def chat(self, messages):
                # LLM thinks "comparison" → would normally route to graph
                return (
                    '{"intent": "comparison", "rewritten_query": "x", '
                    '"sub_queries": [], "keywords": []}'
                )

        with (
            patch("llm.create_llm", return_value=FakeLLM()),
            patch.object(nodes, "load_prompt", return_value="prompt"),
        ):
            result = await nodes.analyze_query(
                {"query": "Apple vs Samsung", "forced_strategy": "vector"}
            )

        assert result["parsed_query"]["retrieval_strategy"] == "vector"
        assert result["parsed_query"]["strategy_reason"] == "caller_override"

    @pytest.mark.asyncio
    async def test_analyze_query_routing_survives_llm_failure(self):
        """LLM down → fallback parsed_query → routing rules still apply."""
        from src.agent import nodes

        class BrokenLLM:
            async def chat(self, messages):
                raise RuntimeError("LLM API down")

        with (
            patch("llm.create_llm", return_value=BrokenLLM()),
            patch.object(nodes, "load_prompt", return_value="prompt"),
        ):
            result = await nodes.analyze_query({"query": "what is happening"})

        # Fallback intent is "factual" with naive split keywords;
        # no entity match → hybrid
        assert result["parsed_query"]["retrieval_strategy"] == "hybrid"


# ---------------------------------------------------------------------
# retrieve / re_search integration tests
# ---------------------------------------------------------------------


class TestRetrieveForwardsStrategy:
    @pytest.mark.asyncio
    async def test_retrieve_forwards_strategy_kwarg(self):
        from src.agent import nodes

        captured: dict = {}

        class CapturingRetriever:
            async def retrieve(self, query, top_k, **kwargs):
                captured["query"] = query
                captured["top_k"] = top_k
                captured.update(kwargs)
                return [{"title": "T", "content": "C", "score": 0.5}]

        class FakeRuntime:
            def create_retriever(self):
                return CapturingRetriever()

        state = {
            "runtime": FakeRuntime(),
            "search_plan": {"queries": ["q1"], "per_query": 3, "total": 5},
            "parsed_query": {"retrieval_strategy": "graph"},
            "top_k": 5,
        }
        await nodes.retrieve(state)
        assert captured["strategy"] == "graph"

    @pytest.mark.asyncio
    async def test_retrieve_gracefully_handles_retriever_without_strategy_kwarg(self):
        """Legacy retrievers (FakeRetriever in older tests) get the old signature."""
        from src.agent import nodes

        class OldRetriever:
            def __init__(self):
                self.calls = []

            async def retrieve(self, query, top_k):
                self.calls.append((query, top_k))
                return [{"title": "x", "content": "y", "score": 0.5}]

        old = OldRetriever()

        class FakeRuntime:
            def create_retriever(self):
                return old

        state = {
            "runtime": FakeRuntime(),
            "search_plan": {"queries": ["q1"], "per_query": 3, "total": 5},
            "parsed_query": {"retrieval_strategy": "graph"},
            "top_k": 5,
        }
        result = await nodes.retrieve(state)
        assert len(old.calls) == 1
        # Result still propagates
        assert len(result["retrieval_results"]) == 1

    @pytest.mark.asyncio
    async def test_retrieve_defaults_to_hybrid_when_parsed_query_missing(self):
        from src.agent import nodes

        captured: dict = {}

        class CapturingRetriever:
            async def retrieve(self, query, top_k, **kwargs):
                captured.update(kwargs)
                return []

        class FakeRuntime:
            def create_retriever(self):
                return CapturingRetriever()

        state = {
            "runtime": FakeRuntime(),
            "search_plan": {"queries": ["q1"], "per_query": 3, "total": 5},
            "top_k": 5,
        }
        await nodes.retrieve(state)
        assert captured.get("strategy") == "hybrid"


# ---------------------------------------------------------------------
# Runtime → GraphRetriever wiring
# ---------------------------------------------------------------------


class TestRuntimeGraphRetriever:
    def test_create_retriever_includes_graph_when_enabled(self, monkeypatch):
        """Runtime wires GraphRetriever into MultiPathRetriever when settings allow."""
        from src.agent.runtime import AgentRuntime

        runtime = AgentRuntime()
        # Force the graph store + retriever construction to succeed via mocks.
        # Patch path is resolved at runtime — pytest test ordering can leave
        # only `src.graph.neo4j_store` in sys.modules, so the production code
        # falls back to that spelling and a hardcoded bare-spelling patch
        # becomes a no-op.
        with (
            patch(_neo4j_store_patch_target()) as mock_store_cls,
            patch("vectorstore.MilvusStore"),
        ):
            mock_store_cls.return_value = object()
            retriever = runtime.create_retriever()

        assert retriever.graph_retriever is not None

    def test_create_graph_retriever_returns_none_when_disabled(self, monkeypatch):
        from src.agent.runtime import AgentRuntime

        runtime = AgentRuntime()
        monkeypatch.setattr(runtime.config, "graph_enabled", False)
        assert runtime.create_graph_retriever() is None

    def test_create_graph_retriever_swallows_init_errors(self, monkeypatch):
        """Neo4j down at boot → degrade to vector-only, don't crash."""
        from src.agent.runtime import AgentRuntime

        runtime = AgentRuntime()
        monkeypatch.setattr(runtime.config, "graph_enabled", True)
        # Same dual-spelling resolution as above — see _neo4j_store_patch_target.
        with patch(
            _neo4j_store_patch_target(),
            side_effect=RuntimeError("Neo4j unreachable"),
        ):
            assert runtime.create_graph_retriever() is None
