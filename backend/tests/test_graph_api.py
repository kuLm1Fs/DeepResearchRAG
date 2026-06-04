"""Tests for the Phase 5 graph introspection API + graph_facts SSE event.

Two surfaces covered:
  - /api/graph/{stats,entity,related,rebuild} endpoints (HTTP layer)
  - ``graph_facts`` event emitted by ``run_agent_stream`` (SSE layer)

The Neo4j driver is never actually exercised — every store method the
endpoints call is patched. The point of these tests is to lock the
contract: what the API returns, what event shape hits the wire, and
that graph-disabled / store-down paths degrade cleanly instead of
500ing.
"""
from __future__ import annotations

import asyncio
import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------
# Neo4jStore patch path resolver
# ---------------------------------------------------------------------

def _neo4j_store_path() -> str:
    """Resolve the patch target the same way the API router does at runtime.

    The conftest adds ``src`` to sys.path so the API router resolves
    ``from graph.neo4j_store import Neo4jStore`` to ``src/graph/neo4j_store.py``.
    But pytest also discovers ``tests/graph/`` (which has its own __init__.py
    and a test_neo4j_store.py), and depending on import order ``graph`` may
    end up referring to ``tests.graph`` (the test package). In that state
    ``import graph.neo4j_store`` raises ModuleNotFoundError. We tolerate it
    by preferring whichever spelling is already in sys.modules, and falling
    back to an explicit ``src.graph.neo4j_store`` import.
    """
    if "src.graph.neo4j_store" in sys.modules:
        return "src.graph.neo4j_store.Neo4jStore"
    if "graph.neo4j_store" in sys.modules:
        # Could be tests.graph.neo4j_store in edge cases — verify it's
        # actually the production module by checking its file path.
        mod = sys.modules["graph.neo4j_store"]
        if getattr(mod, "__file__", "") and "src/graph" in mod.__file__:
            return "graph.neo4j_store.Neo4jStore"
    # Neither cached: import via the explicit src.* spelling (always works
    # because conftest puts the backend dir on sys.path).
    import src.graph.neo4j_store  # noqa: F401
    return "src.graph.neo4j_store.Neo4jStore"


# ---------------------------------------------------------------------
# Stub: fake authenticated user for endpoint tests
# ---------------------------------------------------------------------

class _StubUser:
    id = "user-1"
    company_id = "co-1"
    role = "user"


# ---------------------------------------------------------------------
# /api/graph/stats
# ---------------------------------------------------------------------

# The graph router module does ``from core import settings`` — and pytest's
# sys.path layout gives ``core`` and ``src.core`` separate module entries
# with separate Settings() instances. To patch the *same* settings object
# the router reads, we always patch via ``core.settings`` (the import path
# used in graph.py). Otherwise the router keeps seeing the unpatched
# value and the test degenerates.
def _router_settings():
    import core  # noqa: WPS433 - late import on purpose
    return core.settings


class TestGraphStatsEndpoint:
    @pytest.mark.asyncio
    async def test_stats_returns_empty_when_graph_disabled(self):
        from src.api import graph as graph_api

        with patch.object(_router_settings(), "graph_enabled", False):
            result = await graph_api.graph_stats(current_user=_StubUser())

        assert result.enabled is False
        assert result.counts == {}
        assert result.top_entities == []

    @pytest.mark.asyncio
    async def test_stats_returns_counts_and_top_entities(self):
        from src.api import graph as graph_api

        fake_store = MagicMock()
        fake_store.stats = AsyncMock(return_value={"Entity": 42, "Chunk": 100, "Document": 17})
        fake_store.top_entities = AsyncMock(
            return_value=[
                {"entity_id": "e1", "name": "Apple", "type": "Company", "mention_count": 9},
                {"entity_id": "e2", "name": "TSMC", "type": "Company", "mention_count": 5},
            ]
        )
        with (
            patch.object(_router_settings(), "graph_enabled", True),
            patch(_neo4j_store_path(), return_value=fake_store),
        ):
            result = await graph_api.graph_stats(current_user=_StubUser())

        assert result.enabled is True
        assert result.counts == {"Entity": 42, "Chunk": 100, "Document": 17}
        assert len(result.top_entities) == 2
        assert result.top_entities[0].name == "Apple"
        assert result.top_entities[0].mention_count == 9

    @pytest.mark.asyncio
    async def test_stats_degrades_on_store_error(self):
        # Use the same class instance the router imports — ``core.errors``
        # resolves to the same module the graph router sees at runtime.
        from core.errors import GraphStoreError
        from src.api import graph as graph_api

        fake_store = MagicMock()
        fake_store.stats = AsyncMock(side_effect=GraphStoreError("neo4j down"))
        fake_store.top_entities = AsyncMock(return_value=[])
        with (
            patch.object(_router_settings(), "graph_enabled", True),
            patch(_neo4j_store_path(), return_value=fake_store),
        ):
            result = await graph_api.graph_stats(current_user=_StubUser())

        # Degrade rather than raise — the sidebar should still render.
        assert result.enabled is True
        assert result.counts == {}


# ---------------------------------------------------------------------
# /api/graph/entity/{name}
# ---------------------------------------------------------------------

class TestEntitySubgraphEndpoint:
    @pytest.mark.asyncio
    async def test_entity_subgraph_returns_normalized_payload(self):
        from src.api import graph as graph_api

        fake_store = MagicMock()
        fake_store.entity_subgraph = AsyncMock(
            return_value={
                "entity_id": "apple:Company",
                "name": "Apple",
                "type": "Company",
                "description": "Technology company",
                "mention_count": 12,
                "relations": [
                    {
                        "type": "supplies",
                        "target_id": "tsmc:Company",
                        "target_name": "TSMC",
                        "target_type": "Company",
                        "weight": 0.9,
                        "description": "TSMC supplies chips to Apple",
                    },
                    # OPTIONAL MATCH arm returning None should be filtered
                    None,
                ],
                "sample_chunks": [
                    {"chunk_id": "c1", "content": "Apple ...", "title": "T1", "url": "", "source": "rss"},
                ],
            }
        )
        with (
            patch.object(_router_settings(), "graph_enabled", True),
            patch(_neo4j_store_path(), return_value=fake_store),
        ):
            result = await graph_api.entity_subgraph(name="Apple", current_user=_StubUser())

        assert result.name == "Apple"
        assert result.entity_id == "apple:Company"
        assert len(result.relations) == 1  # None filtered
        assert result.relations[0].target_name == "TSMC"
        assert len(result.sample_chunks) == 1

    @pytest.mark.asyncio
    async def test_entity_subgraph_404_when_not_found(self):
        from fastapi import HTTPException

        from src.api import graph as graph_api

        fake_store = MagicMock()
        fake_store.entity_subgraph = AsyncMock(return_value=None)
        with (
            patch.object(_router_settings(), "graph_enabled", True),
            patch(_neo4j_store_path(), return_value=fake_store),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await graph_api.entity_subgraph(name="Unknown", current_user=_StubUser())
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_entity_subgraph_503_when_graph_disabled(self):
        from fastapi import HTTPException

        from src.api import graph as graph_api

        with patch.object(_router_settings(), "graph_enabled", False):
            with pytest.raises(HTTPException) as exc_info:
                await graph_api.entity_subgraph(name="Apple", current_user=_StubUser())
        assert exc_info.value.status_code == 503


# ---------------------------------------------------------------------
# /api/graph/related/{chunk_id}
# ---------------------------------------------------------------------

class TestChunkRelatedEndpoint:
    @pytest.mark.asyncio
    async def test_chunk_related_returns_entities_and_relations(self):
        from src.api import graph as graph_api

        fake_store = MagicMock()
        fake_store.chunk_graph = AsyncMock(
            return_value=[
                {
                    "entity_id": "apple:Company",
                    "name": "Apple",
                    "type": "Company",
                    "relations": [{"type": "competes_with", "target": "Samsung"}],
                },
                {
                    "entity_id": "tsmc:Company",
                    "name": "TSMC",
                    "type": "Company",
                    "relations": [],
                },
            ]
        )
        with (
            patch.object(_router_settings(), "graph_enabled", True),
            patch(_neo4j_store_path(), return_value=fake_store),
        ):
            result = await graph_api.chunk_related(chunk_id="chunk-1", current_user=_StubUser())

        assert result["chunk_id"] == "chunk-1"
        assert len(result["entities"]) == 2
        apple = next(e for e in result["entities"] if e["name"] == "Apple")
        assert apple["relations"][0]["target"] == "Samsung"


# ---------------------------------------------------------------------
# /api/graph/rebuild
# ---------------------------------------------------------------------

class TestGraphRebuildEndpoint:
    @pytest.mark.asyncio
    async def test_rebuild_skipped_when_graph_disabled(self):
        from src.api import graph as graph_api

        with patch.object(_router_settings(), "graph_enabled", False):
            result = await graph_api.graph_rebuild(
                body=graph_api.RebuildRequest(), current_user=_StubUser()
            )
        assert result.status == "skipped"
        assert "disabled" in result.message.lower()

    @pytest.mark.asyncio
    async def test_rebuild_enqueues_task_and_returns_id(self):
        from src.api import graph as graph_api

        # Patch asyncio.create_task so the background coroutine doesn't actually run
        created_tasks: list[asyncio.Task] = []
        real_create_task = asyncio.create_task

        def capture_task(coro):
            task = real_create_task(coro)
            created_tasks.append(task)
            return task

        with (
            patch.object(_router_settings(), "graph_enabled", True),
            patch.object(asyncio, "create_task", side_effect=capture_task),
        ):
            result = await graph_api.graph_rebuild(
                body=graph_api.RebuildRequest(limit=500),
                current_user=_StubUser(),
            )
        assert result.status == "started"
        assert result.task_id is not None
        assert result.task_id.startswith("graph_rebuild_")

        # Let the captured task finish (it'll silently exit because the
        # build_from_milvus import may not resolve, but no exception
        # should escape — that path is wrapped in try/except).
        if created_tasks:
            try:
                await asyncio.wait_for(created_tasks[0], timeout=1.0)
            except (asyncio.TimeoutError, Exception):
                pass


# ---------------------------------------------------------------------
# build_graph_facts (pure function, no HTTP)
# ---------------------------------------------------------------------

class TestBuildGraphFacts:
    def test_dedupes_entities_across_chunks(self):
        from src.agent.nodes import build_graph_facts

        results = [
            {
                "chunk_id": "c1",
                "via_entities": ["Apple", "TSMC"],
                "via_relations": [{"type": "supplies", "source": "TSMC", "target": "Apple"}],
            },
            {
                "chunk_id": "c2",
                "via_entities": ["Apple", "Samsung"],
                "via_relations": [
                    {"type": "supplies", "source": "TSMC", "target": "Apple"},
                    {"type": "competes_with", "source": "Apple", "target": "Samsung"},
                ],
            },
        ]
        facts = build_graph_facts(
            retrieval_results=results,
            parsed_query={"retrieval_strategy": "graph", "strategy_reason": "intent_is_comparison"},
        )
        names = sorted(e["name"] for e in facts["entities"])
        assert names == ["Apple", "Samsung", "TSMC"]
        assert facts["strategy"] == "graph"
        assert facts["strategy_reason"] == "intent_is_comparison"
        # Two relations: (TSMC, supplies, Apple) deduped, (Apple, competes_with, Samsung) new
        assert len(facts["relations"]) == 2

    def test_empty_results_yields_empty_facts_not_none(self):
        from src.agent.nodes import build_graph_facts

        facts = build_graph_facts(
            retrieval_results=[],
            parsed_query={"retrieval_strategy": "vector"},
        )
        assert facts["entities"] == []
        assert facts["relations"] == []
        assert facts["strategy"] == "vector"

    def test_handles_chunks_without_graph_metadata(self):
        """Vector-only chunks (no via_entities) don't crash the builder."""
        from src.agent.nodes import build_graph_facts

        results = [
            {"chunk_id": "v1", "title": "T", "content": "C"},
            {"chunk_id": "v2", "via_entities": None, "via_relations": None},
        ]
        facts = build_graph_facts(retrieval_results=results, parsed_query={})
        assert facts["entities"] == []
        assert facts["relations"] == []
        assert facts["strategy"] == "hybrid"  # default

    def test_chunk_entity_map_indexes_chunks(self):
        from src.agent.nodes import build_graph_facts

        results = [
            {"chunk_id": "c1", "via_entities": ["Apple"]},
            {"chunk_id": "c2", "via_entities": ["TSMC"]},
        ]
        facts = build_graph_facts(retrieval_results=results, parsed_query={})
        assert facts["highlighted_entity_ids"]["c1"] == ["Apple"]
        assert facts["highlighted_entity_ids"]["c2"] == ["TSMC"]

    def test_search_strategy_overrides_parsed_query(self):
        """search_strategy arg takes precedence over parsed_query.retrieval_strategy."""
        from src.agent.nodes import build_graph_facts

        facts = build_graph_facts(
            retrieval_results=[],
            parsed_query={"retrieval_strategy": "vector"},
            search_strategy="hybrid",
        )
        assert facts["strategy"] == "hybrid"


# ---------------------------------------------------------------------
# graph_facts SSE event in run_agent_stream
# ---------------------------------------------------------------------

class TestGraphFactsSSEEvent:
    @pytest.mark.asyncio
    async def test_run_agent_stream_emits_graph_facts_after_sources(self):
        """The wire sequence must be: sources → graph_facts → token* → done."""
        from src.agent import graph as agent_graph

        # Stub the heavy lifting: prepare_answer_state, generate_answer_stream.
        async def fake_prepare(state):
            return {
                **state,
                "retrieval_results": [
                    {
                        "chunk_id": "c1",
                        "title": "T1",
                        "content": "C1",
                        "source": "rss",
                        "category": "news",
                        "score": 0.9,
                        "via_entities": ["Apple", "TSMC"],
                        "via_relations": [
                            {"type": "supplies", "source": "TSMC", "target": "Apple"},
                        ],
                    },
                ],
                "parsed_query": {"retrieval_strategy": "graph", "strategy_reason": "intent_is_comparison"},
                "search_strategy": "graph",
            }

        async def fake_stream(state):
            for tok in ["Hello", " ", "world"]:
                yield tok

        with (
            patch.object(agent_graph, "prepare_answer_state", side_effect=fake_prepare),
            patch.object(agent_graph, "generate_answer_stream", side_effect=fake_stream),
        ):
            events: list[dict[str, Any]] = []
            async for ev in agent_graph.run_agent_stream(query="q", trace_id="t1"):
                events.append(ev)

        event_types = [e["type"] for e in events]
        assert event_types[0] == "sources"
        # graph_facts is emitted between sources and the first token
        assert "graph_facts" in event_types
        assert event_types.index("graph_facts") < event_types.index("done")
        first_token_idx = next(i for i, t in enumerate(event_types) if t == "token")
        assert event_types.index("graph_facts") < first_token_idx

        # graph_facts payload shape
        gf = next(e for e in events if e["type"] == "graph_facts")
        assert gf["data"]["strategy"] == "graph"
        names = sorted(e["name"] for e in gf["data"]["entities"])
        assert names == ["Apple", "TSMC"]
        assert gf["data"]["highlighted_entity_ids"]["c1"] == ["Apple", "TSMC"]

    @pytest.mark.asyncio
    async def test_run_agent_stream_emits_empty_graph_facts_on_vector_path(self):
        from src.agent import graph as agent_graph

        async def fake_prepare(state):
            return {
                **state,
                "retrieval_results": [],  # no graph hits
                "parsed_query": {"retrieval_strategy": "vector"},
                "search_strategy": "vector",
            }

        async def fake_stream(state):
            if False:
                yield  # pragma: no cover

        with (
            patch.object(agent_graph, "prepare_answer_state", side_effect=fake_prepare),
            patch.object(agent_graph, "generate_answer_stream", side_effect=fake_stream),
        ):
            events: list[dict[str, Any]] = []
            async for ev in agent_graph.run_agent_stream(query="q", trace_id="t2"):
                events.append(ev)

        gf = next(e for e in events if e["type"] == "graph_facts")
        assert gf["data"]["entities"] == []
        assert gf["data"]["strategy"] == "vector"

    @pytest.mark.asyncio
    async def test_run_agent_stream_done_event_includes_graph_facts(self):
        from src.agent import graph as agent_graph

        async def fake_prepare(state):
            return {
                **state,
                "retrieval_results": [
                    {
                        "chunk_id": "c1",
                        "via_entities": ["Apple"],
                        "via_relations": [],
                    },
                ],
                "parsed_query": {"retrieval_strategy": "graph"},
                "search_strategy": "graph",
            }

        async def fake_stream(state):
            return
            yield  # pragma: no cover

        with (
            patch.object(agent_graph, "prepare_answer_state", side_effect=fake_prepare),
            patch.object(agent_graph, "generate_answer_stream", side_effect=fake_stream),
        ):
            done_event = None
            async for ev in agent_graph.run_agent_stream(query="q", trace_id="t3"):
                if ev["type"] == "done":
                    done_event = ev
            assert done_event is not None
            assert "graph_facts" in done_event["data"]
            assert done_event["data"]["graph_facts"]["entities"][0]["name"] == "Apple"
