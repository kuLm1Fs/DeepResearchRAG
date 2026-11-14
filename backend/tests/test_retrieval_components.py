"""Retrieval component switches. Defaults stay on the historical path."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.retrieval.cache import RetrievalPathCache
from src.retrieval.components import (
    ABLATION_PRESETS,
    RetrievalComponents,
    parse_ablation_configs,
)
from src.retrieval.retriever import MultiPathRetriever


def _doc(key: str, score: float, title: str = "t", content: str = "c") -> dict:
    return {
        "content_hash": key,
        "chunk_id": key,
        "title": title,
        "content": content,
        "score": score,
        "published_at": 0,
        "source": "",
    }


class RecordingStore:
    def __init__(self, vector=None, keyword=None, title=None):
        self.vector = list(vector or [])
        self.keyword = list(keyword or [])
        self.title = list(title or [])
        self.search_calls = 0
        self.query_calls = []

    async def search_async(self, **kwargs):
        self.search_calls += 1
        return [dict(item) for item in self.vector]

    async def query_async(self, expr, output_fields=None, limit=100):
        self.query_calls.append({"expr": expr, "output_fields": output_fields, "limit": limit})
        rows = self.keyword if "content like" in expr else self.title
        return [dict(item) for item in rows]


@pytest.fixture
def embed(monkeypatch):
    async def _embed(texts):
        return [[0.1, 0.2] for _ in texts]

    monkeypatch.setattr("src.retrieval.retriever.embed_texts_async", _embed)
    return _embed


def test_settings_default_matches_the_all_on_mask():
    assert RetrievalComponents.from_settings(object()) == RetrievalComponents()

    class DisabledBm25:
        retrieval_bm25 = False

    parsed = RetrievalComponents.from_settings(DisabledBm25())
    assert parsed.bm25 is False
    assert parsed.vector is True
    assert parsed != RetrievalComponents()


def test_ablation_presets_match_the_requested_matrix():
    vector = ABLATION_PRESETS["vector"]
    assert vector.vector and not vector.bm25 and not vector.title
    assert not any(
        [vector.rrf, vector.reranker, vector.time_decay, vector.source_weight, vector.graph]
    )

    assert ABLATION_PRESETS["bm25"].bm25 and not ABLATION_PRESETS["bm25"].vector
    assert ABLATION_PRESETS["title"].title and not ABLATION_PRESETS["title"].bm25

    fused = ABLATION_PRESETS["vector_bm25"]
    assert fused.vector and fused.bm25 and fused.rrf
    assert not fused.title and not fused.reranker and not fused.time_decay

    three = ABLATION_PRESETS["vector_bm25_title"]
    assert three.vector and three.bm25 and three.title and three.rrf
    assert not three.reranker and not three.time_decay and not three.source_weight

    full = ABLATION_PRESETS["full"]
    assert all(
        [
            full.vector,
            full.bm25,
            full.title,
            full.rrf,
            full.reranker,
            full.time_decay,
            full.source_weight,
        ]
    )
    assert full.graph is False

    assert parse_ablation_configs("vector+bm25, full") == ["vector_bm25", "full"]


@pytest.mark.asyncio
async def test_default_retriever_still_runs_all_milvus_paths_and_boosts(embed):
    store = RecordingStore(vector=[_doc("v", 0.4)])
    retriever = MultiPathRetriever(store, rerank_enabled=False)

    results = await retriever.retrieve("alpha revenue", top_k=5)

    assert retriever.components is None
    assert store.search_calls == 1
    assert len(store.query_calls) == 2
    assert "content like" in store.query_calls[0]["expr"]
    assert "title like" in store.query_calls[1]["expr"]
    assert "content like" not in store.query_calls[1]["expr"]
    assert "chunk_id" in store.query_calls[0]["output_fields"]
    assert "chunk_id" in store.query_calls[1]["output_fields"]
    assert "boosted_score" in results[0]


@pytest.mark.asyncio
async def test_single_paths_skip_the_other_milvus_calls(embed):
    store = RecordingStore(
        vector=[_doc("v", 0.9)],
        keyword=[_doc("k", 0.5)],
        title=[_doc("t", 0.8)],
    )

    vector = MultiPathRetriever(store, components=ABLATION_PRESETS["vector"])
    await vector.retrieve("alpha revenue", top_k=5)
    assert store.search_calls == 1
    assert store.query_calls == []

    bm25 = MultiPathRetriever(store, components=ABLATION_PRESETS["bm25"])
    await bm25.retrieve("alpha revenue", top_k=5)
    assert store.search_calls == 1
    assert len(store.query_calls) == 1
    assert "content like" in store.query_calls[0]["expr"]

    title = MultiPathRetriever(store, components=ABLATION_PRESETS["title"])
    await title.retrieve("alpha revenue", top_k=5)
    assert store.search_calls == 1
    assert len(store.query_calls) == 2
    assert "title like" in store.query_calls[1]["expr"]
    assert "content like" not in store.query_calls[1]["expr"]


@pytest.mark.asyncio
async def test_rrf_keeps_fusion_order_until_time_decay_is_enabled(embed):
    shared = _doc("a", 0.2)
    vector_only = _doc("b", 0.9)
    store = RecordingStore(vector=[shared, vector_only], keyword=[dict(shared)])

    without_boost = MultiPathRetriever(store, components=ABLATION_PRESETS["vector_bm25"])
    fused = await without_boost.retrieve("alpha revenue", top_k=5)
    assert [item["content_hash"] for item in fused] == ["a", "b"]
    assert "boosted_score" not in fused[0]
    assert all("content like" in call["expr"] for call in store.query_calls)
    assert not any(
        "title like" in call["expr"] and "content like" not in call["expr"]
        for call in store.query_calls
    )

    with_boost = MultiPathRetriever(
        store,
        components=RetrievalComponents(
            vector=True,
            bm25=True,
            title=False,
            rrf=True,
            reranker=False,
            time_decay=True,
            source_weight=True,
            graph=False,
        ),
    )
    boosted = await with_boost.retrieve("alpha revenue", top_k=5)
    assert [item["content_hash"] for item in boosted] == ["b", "a"]


@pytest.mark.asyncio
async def test_rrf_off_keeps_path_order(embed):
    store = RecordingStore(vector=[_doc("b", 0.9)], keyword=[_doc("a", 0.1)])
    retriever = MultiPathRetriever(
        store,
        components=RetrievalComponents(
            vector=True,
            bm25=True,
            title=False,
            rrf=False,
            reranker=False,
            time_decay=False,
            source_weight=False,
            graph=False,
        ),
    )

    results = await retriever.retrieve("alpha revenue", top_k=5)

    assert [item["content_hash"] for item in results] == ["b", "a"]


@pytest.mark.asyncio
async def test_reranker_and_graph_follow_the_component_mask(embed):
    store = RecordingStore(vector=[_doc("v", 0.4, content="alpha revenue details")])
    graph = MagicMock()
    graph.retrieve = AsyncMock(return_value=[_doc("g", 0.7)])

    def _rerank(self, query, results, top_k):
        flipped = []
        for item in reversed(results):
            copied = dict(item)
            copied["rerank_score"] = 1.0
            flipped.append(copied)
        return flipped[:top_k]

    with patch("src.retrieval.reranker.CrossEncoderReranker.rerank", _rerank):
        plain = MultiPathRetriever(
            store,
            components=ABLATION_PRESETS["vector"],
            graph_retriever=graph,
        )
        plain_results = await plain.retrieve("alpha revenue", top_k=5)
        graph.retrieve.assert_not_awaited()
        assert "rerank_score" not in plain_results[0]

        full = MultiPathRetriever(
            store,
            components=ABLATION_PRESETS["full"],
            graph_retriever=graph,
        )
        full_results = await full.retrieve("alpha revenue", top_k=5)

    graph.retrieve.assert_not_awaited()
    assert "rerank_score" in full_results[0]


@pytest.mark.asyncio
async def test_path_cache_skips_a_second_vector_call(embed, tmp_path):
    store = RecordingStore(vector=[_doc("v", 0.4)])
    cache = RetrievalPathCache(tmp_path / "cache")
    retriever = MultiPathRetriever(
        store,
        components=ABLATION_PRESETS["vector"],
        path_cache=cache,
    )

    first = await retriever.retrieve("alpha revenue", top_k=5)
    first_latency = retriever.last_retrieval_latency_ms
    second = await retriever.retrieve("alpha revenue", top_k=5)

    assert store.search_calls == 1
    assert [item["content_hash"] for item in second] == [item["content_hash"] for item in first]
    assert retriever.last_retrieval_latency_ms == pytest.approx(first_latency, rel=0.5, abs=50)
    assert list((tmp_path / "cache").glob("*.json"))


def test_runtime_passes_components_only_when_a_stage_is_disabled(monkeypatch):
    from src.agent.runtime import AgentRuntime

    captured = {}

    class FakeConfig:
        graph_enabled = False
        degradation_enabled = True
        retrieval_title = False

    class FakeRetriever:
        def __init__(
            self,
            store,
            graph_retriever=None,
            fault_injector=None,
            degradation_policy=None,
            components=None,
        ):
            captured["components"] = components

    monkeypatch.setattr("vectorstore.MilvusStore", lambda: object())
    monkeypatch.setattr("retrieval.MultiPathRetriever", FakeRetriever)

    AgentRuntime(config=FakeConfig()).create_retriever()

    assert captured["components"] is not None
    assert captured["components"].title is False
    assert captured["components"].vector is True

    class DefaultConfig:
        graph_enabled = False
        degradation_enabled = True

    captured.clear()
    AgentRuntime(config=DefaultConfig()).create_retriever()
    assert captured["components"] is None
