"""Tests for the GraphRetriever (Phase 3 of GraphRAG).

The graph path is mocked end-to-end — we never hit Neo4j in unit tests.
We verify the *plumbing*:

  - entity path: vector_search_entities -> entity_neighbors_chunks -> chunks
  - relation path: fulltext_search_relations -> chunks
  - merge: dedupes by chunk_id, averages scores, accumulates via_entities/via_relations
  - error isolation: a failing path returns [] but doesn't break the other
  - empty graph: returns [] without calling the store
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _entity(eid: str, name: str, score: float, type_: str = "Company") -> dict:
    return {
        "entity_id": eid,
        "name": name,
        "type": type_,
        "description": f"description for {name}",
        "score": score,
    }


def _neighbor(chunk_id: str, content: str, title: str, via_relations: list | None = None) -> dict:
    return {
        "chunk_id": chunk_id,
        "content": content,
        "title": title,
        "url": f"https://example.com/{chunk_id}",
        "source": "TestSource",
        "via_relations": via_relations or [],
    }


def _relation_row(
    chunk_id: str,
    content: str,
    title: str,
    rel_type: str,
    src: str,
    tgt: str,
    score: float,
) -> dict:
    return {
        "chunk_id": chunk_id,
        "content": content,
        "title": title,
        "url": f"https://example.com/{chunk_id}",
        "source": "TestSource",
        "relation_type": rel_type,
        "source_entity": src,
        "target_entity": tgt,
        "score": score,
    }


def _mock_store(
    entities: list | None = None,
    neighbors_by_entity: dict | None = None,
    relations: list | None = None,
    *,
    entity_error: Exception | None = None,
    neighbor_error: Exception | None = None,
    relation_error: Exception | None = None,
):
    """Build a mock Neo4jStore with canned responses."""
    store = MagicMock()
    store.vector_search_entities = AsyncMock(
        side_effect=entity_error or (lambda emb, top_k: entities or [])
    )
    neighbors = neighbors_by_entity or {}
    async def _neighbors(entity_id):
        if neighbor_error:
            raise neighbor_error
        return neighbors.get(entity_id, [])
    store.entity_neighbors_chunks = AsyncMock(side_effect=_neighbors)
    store.fulltext_search_relations = AsyncMock(
        side_effect=relation_error or (lambda q, top_k: relations or [])
    )
    return store


def _patched_embed(return_value: list[list[float]] | None = None):
    """Mock the embedding function. Default: a single 1024-dim zero vector.

    Patches the bound name ``embed_texts_async`` on
    ``src.retrieval.graph_retriever`` (the same module the production
    code imports it into). Patching the underlying
    ``vectorstore.embedding.embed_texts_async`` would not affect calls
    made from inside ``graph_retriever`` because of Python's name
    binding at import time.
    """
    if return_value is None:
        return_value = [[0.0] * 1024]
    return patch(
        "src.retrieval.graph_retriever.embed_texts_async",
        new=AsyncMock(return_value=return_value),
    )


class TestGraphRetrieverEmpty:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_entities(self):
        from src.retrieval.graph_retriever import GraphRetriever

        store = _mock_store(entities=[], relations=[])
        with _patched_embed():
            retriever = GraphRetriever(store)
            result = await retriever.retrieve("anything", top_k=10)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_embed_fails(self):
        from src.retrieval.graph_retriever import GraphRetriever

        store = _mock_store(entities=[_entity("e1", "苹果", 0.9)])
        with patch(
            "src.retrieval.graph_retriever.embed_texts_async",
            new=AsyncMock(side_effect=RuntimeError("embedding API down")),
        ):
            retriever = GraphRetriever(store)
            result = await retriever.retrieve("query", top_k=10)
        assert result == []


class TestGraphRetrieverEntityPath:
    @pytest.mark.asyncio
    async def test_entity_path_returns_neighbor_chunks(self):
        from src.retrieval.graph_retriever import GraphRetriever

        store = _mock_store(
            entities=[_entity("苹果:Company", "苹果", 0.92)],
            neighbors_by_entity={
                "苹果:Company": [
                    _neighbor("c1", "Apple Q3 earnings beat", "Apple Q3", [
                        {"type": "led_by", "target": "Tim Cook", "weight": 0.9}
                    ])
                ]
            },
        )
        with _patched_embed():
            retriever = GraphRetriever(store)
            result = await retriever.retrieve("苹果公司", top_k=5)
        assert len(result) == 1
        chunk = result[0]
        assert chunk["chunk_id"] == "c1"
        assert chunk["score"] == 0.92
        assert chunk["via_entities"] == ["苹果"]
        assert chunk["retrieval_path"] == "graph_entity"
        assert len(chunk["via_relations"]) == 1
        assert chunk["via_relations"][0]["type"] == "led_by"

    @pytest.mark.asyncio
    async def test_entity_path_caps_neighbors_per_entity(self):
        from src.retrieval.graph_retriever import GraphRetriever

        # Entity has 5 neighbors; we cap at 2.
        store = _mock_store(
            entities=[_entity("e1", "苹果", 0.9)],
            neighbors_by_entity={
                "e1": [
                    _neighbor(f"c{i}", f"content {i}", f"title {i}")
                    for i in range(5)
                ]
            },
        )
        with _patched_embed():
            retriever = GraphRetriever(store, max_neighbors_per_entity=2)
            result = await retriever.retrieve("query", top_k=10)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_entity_path_skips_failed_neighbors(self):
        from src.retrieval.graph_retriever import GraphRetriever

        store = _mock_store(
            entities=[_entity("e1", "苹果", 0.9), _entity("e2", "微软", 0.8)],
            neighbors_by_entity={
                "e1": [_neighbor("c1", "x", "y")],
                # e2 not in neighbors map -> _neighbors returns []
            },
        )
        with _patched_embed():
            retriever = GraphRetriever(store)
            result = await retriever.retrieve("query", top_k=10)
        assert len(result) == 1
        assert result[0]["chunk_id"] == "c1"


class TestGraphRetrieverRelationPath:
    @pytest.mark.asyncio
    async def test_relation_path_returns_chunks(self):
        from src.retrieval.graph_retriever import GraphRetriever

        store = _mock_store(
            relations=[
                _relation_row("c1", "Apple invested in TSMC", "Apple-TSMC deal",
                              "invested_in", "苹果", "tsmc", 0.85),
            ]
        )
        with _patched_embed():
            retriever = GraphRetriever(store)
            result = await retriever.retrieve("supply chain", top_k=5)
        assert len(result) == 1
        chunk = result[0]
        assert chunk["chunk_id"] == "c1"
        assert chunk["score"] == 0.85
        assert chunk["retrieval_path"] == "graph_relation"
        assert "苹果" in chunk["via_entities"]
        assert "tsmc" in chunk["via_entities"]
        assert chunk["via_relations"][0]["type"] == "invested_in"


class TestGraphRetrieverMerge:
    @pytest.mark.asyncio
    async def test_merge_dedupes_by_chunk_id(self):
        """Same chunk hit by both paths: averaged score, merged metadata."""
        from src.retrieval.graph_retriever import GraphRetriever

        store = _mock_store(
            entities=[_entity("苹果:Company", "苹果", 0.8)],
            neighbors_by_entity={
                "苹果:Company": [_neighbor("c1", "Apple content", "Apple title")],
            },
            relations=[
                _relation_row("c1", "Apple content", "Apple title",
                              "competes_with", "苹果", "samsung", 0.6),
            ],
        )
        with _patched_embed():
            retriever = GraphRetriever(store)
            result = await retriever.retrieve("Apple", top_k=5)
        assert len(result) == 1
        chunk = result[0]
        # Both paths hit it → score is averaged
        assert chunk["score"] == pytest.approx((0.8 + 0.6) / 2)
        # retrieval_path indicates both
        assert "graph_entity" in chunk["retrieval_path"]
        assert "graph_relation" in chunk["retrieval_path"]
        # via_entities accumulated
        assert "苹果" in chunk["via_entities"]
        assert "samsung" in chunk["via_entities"]
        # via_relations accumulated
        assert len(chunk["via_relations"]) == 1
        assert chunk["via_relations"][0]["type"] == "competes_with"

    @pytest.mark.asyncio
    async def test_merge_sorts_by_score_desc(self):
        from src.retrieval.graph_retriever import GraphRetriever

        store = _mock_store(
            relations=[
                _relation_row("c1", "low", "Low", "x", "a", "b", 0.3),
                _relation_row("c2", "high", "High", "y", "c", "d", 0.95),
                _relation_row("c3", "mid", "Mid", "z", "e", "f", 0.6),
            ]
        )
        with _patched_embed():
            retriever = GraphRetriever(store)
            result = await retriever.retrieve("q", top_k=10)
        assert [c["chunk_id"] for c in result] == ["c2", "c3", "c1"]

    @pytest.mark.asyncio
    async def test_merge_respects_top_k(self):
        from src.retrieval.graph_retriever import GraphRetriever

        store = _mock_store(
            relations=[
                _relation_row(f"c{i}", f"content {i}", f"title {i}", "x", "a", "b", 1.0 - i * 0.1)
                for i in range(10)
            ]
        )
        with _patched_embed():
            retriever = GraphRetriever(store)
            result = await retriever.retrieve("q", top_k=3)
        assert len(result) == 3
        # Top 3 by score: c0 (1.0), c1 (0.9), c2 (0.8)
        assert [c["chunk_id"] for c in result] == ["c0", "c1", "c2"]


class TestGraphRetrieverErrorIsolation:
    @pytest.mark.asyncio
    async def test_entity_path_failure_does_not_break_relation(self):
        from src.retrieval.graph_retriever import GraphRetriever

        # Entity path raises, relation path returns valid data
        store = _mock_store(
            relations=[
                _relation_row("c1", "x", "y", "r", "a", "b", 0.5),
            ]
        )
        # Override entity to raise
        store.vector_search_entities = AsyncMock(side_effect=RuntimeError("Neo4j down"))
        with _patched_embed():
            retriever = GraphRetriever(store)
            result = await retriever.retrieve("q", top_k=5)
        # Relation path still works
        assert len(result) == 1
        assert result[0]["chunk_id"] == "c1"

    @pytest.mark.asyncio
    async def test_relation_path_failure_does_not_break_entity(self):
        from src.retrieval.graph_retriever import GraphRetriever

        store = _mock_store(
            entities=[_entity("e1", "苹果", 0.9)],
            neighbors_by_entity={
                "e1": [_neighbor("c1", "Apple content", "Apple title")]
            },
        )
        store.fulltext_search_relations = AsyncMock(side_effect=RuntimeError("index missing"))
        with _patched_embed():
            retriever = GraphRetriever(store)
            result = await retriever.retrieve("q", top_k=5)
        assert len(result) == 1
        assert result[0]["chunk_id"] == "c1"


class TestMultiPathRetrieverWithGraph:
    """Verify that MultiPathRetriever picks up the graph path when configured."""

    @pytest.mark.asyncio
    async def test_hybrid_strategy_runs_graph_path(self):
        from src.retrieval.graph_retriever import GraphRetriever
        from src.retrieval.retriever import MultiPathRetriever

        graph = MagicMock(spec=GraphRetriever)
        graph.retrieve = AsyncMock(return_value=[
            {
                "chunk_id": "g1", "content": "graph content", "title": "g title",
                "url": "u", "source": "S", "score": 0.7,
                "via_entities": ["苹果"], "via_relations": [],
            }
        ])
        store = MagicMock()
        # Three Milvus paths return empty
        store.search_async = AsyncMock(return_value=[])
        store.query_async = AsyncMock(return_value=[])

        retriever = MultiPathRetriever(
            store=store,
            graph_retriever=graph,
            rerank_enabled=False,
        )
        with patch("src.retrieval.retriever.embed_texts_async",
                   new=AsyncMock(return_value=[[0.0] * 1024])):
            results = await retriever.retrieve("苹果", top_k=5, strategy="hybrid")
        graph.retrieve.assert_awaited_once()
        assert len(results) == 1
        assert results[0]["chunk_id"] == "g1"

    @pytest.mark.asyncio
    async def test_vector_strategy_skips_graph(self):
        from src.retrieval.graph_retriever import GraphRetriever
        from src.retrieval.retriever import MultiPathRetriever

        graph = MagicMock(spec=GraphRetriever)
        graph.retrieve = AsyncMock(return_value=[])
        store = MagicMock()
        # Milvus returns 1 result
        milvus_chunk = {
            "id": 1, "chunk_id": "m1", "content": "m content", "title": "m title",
            "source": "S", "score": 0.8, "published_at": 0,
        }
        store.search_async = AsyncMock(return_value=[milvus_chunk])
        store.query_async = AsyncMock(return_value=[])

        retriever = MultiPathRetriever(
            store=store,
            graph_retriever=graph,
            rerank_enabled=False,
        )
        with patch("src.retrieval.retriever.embed_texts_async",
                   new=AsyncMock(return_value=[[0.0] * 1024])):
            results = await retriever.retrieve("query", top_k=5, strategy="vector")
        graph.retrieve.assert_not_awaited()
        # The Milvus chunk should be in results
        assert any(r["chunk_id"] == "m1" for r in results)

    @pytest.mark.asyncio
    async def test_graph_strategy_skips_milvus(self):
        from src.retrieval.graph_retriever import GraphRetriever
        from src.retrieval.retriever import MultiPathRetriever

        graph = MagicMock(spec=GraphRetriever)
        graph.retrieve = AsyncMock(return_value=[
            {"chunk_id": "g1", "content": "x", "title": "t", "score": 0.9}
        ])
        store = MagicMock()
        store.search_async = AsyncMock(return_value=[])
        store.query_async = AsyncMock(return_value=[])

        retriever = MultiPathRetriever(
            store=store,
            graph_retriever=graph,
            rerank_enabled=False,
        )
        results = await retriever.retrieve("query", top_k=5, strategy="graph")
        # Milvus not called
        store.search_async.assert_not_awaited()
        store.query_async.assert_not_awaited()
        # Graph only
        assert len(results) == 1
        assert results[0]["chunk_id"] == "g1"

    @pytest.mark.asyncio
    async def test_no_graph_retriever_falls_back_to_3_path(self):
        """If graph_retriever is None, hybrid still works with 3 paths."""
        from src.retrieval.retriever import MultiPathRetriever

        store = MagicMock()
        milvus_chunk = {
            "id": 1, "chunk_id": "m1", "content": "m", "title": "t",
            "source": "S", "score": 0.5, "published_at": 0,
        }
        store.search_async = AsyncMock(return_value=[milvus_chunk])
        store.query_async = AsyncMock(return_value=[])

        retriever = MultiPathRetriever(
            store=store,
            graph_retriever=None,
            rerank_enabled=False,
        )
        with patch("src.retrieval.retriever.embed_texts_async",
                   new=AsyncMock(return_value=[[0.0] * 1024])):
            results = await retriever.retrieve("q", top_k=5, strategy="hybrid")
        assert any(r["chunk_id"] == "m1" for r in results)
