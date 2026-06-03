"""Tests for the Phase 6 graph metrics added to ``src.eval.metrics``."""
from src.eval.metrics import (
    aggregate_graphrag_metrics,
    entity_recall,
    graph_path_hit_rate,
    latency_summary,
)


class TestEntityRecall:
    def test_empty_expected_returns_zero(self):
        assert entity_recall(["Apple"], []) == 0.0

    def test_empty_retrieved_returns_zero(self):
        assert entity_recall([], ["Apple"]) == 0.0

    def test_full_match(self):
        assert entity_recall(["Apple", "TSMC"], ["Apple", "TSMC"]) == 1.0

    def test_partial_match(self):
        assert entity_recall(["Apple"], ["Apple", "TSMC"]) == 0.5

    def test_case_insensitive(self):
        assert entity_recall(["APPLE"], ["apple"]) == 1.0

    def test_extra_retrieved_doesnt_penalize(self):
        # entity_recall is "did we cover expected?" — extras are free
        assert entity_recall(["Apple", "TSMC", "Samsung"], ["Apple"]) == 1.0


class TestGraphPathHitRate:
    def test_no_results(self):
        assert graph_path_hit_rate([]) == 0.0

    def test_all_graph(self):
        results = [
            {"retrieval_path": "graph", "chunk_id": "1"},
            {"retrieval_path": "graph", "chunk_id": "2"},
        ]
        assert graph_path_hit_rate(results) == 1.0

    def test_mixed(self):
        results = [
            {"retrieval_path": "graph", "chunk_id": "1"},
            {"chunk_id": "2"},  # no path tag → vector/keyword/title
            {"retrieval_path": "graph", "chunk_id": "3"},
        ]
        assert abs(graph_path_hit_rate(results) - 2 / 3) < 1e-9

    def test_all_vector(self):
        results = [{"chunk_id": "1"}, {"chunk_id": "2"}]
        assert graph_path_hit_rate(results) == 0.0


class TestLatencySummary:
    def test_empty(self):
        s = latency_summary([])
        assert s["n"] == 0
        assert s["p50"] == 0.0
        assert s["p95"] == 0.0

    def test_single_value(self):
        s = latency_summary([100.0])
        assert s["n"] == 1
        assert s["p50"] == 100.0
        assert s["p95"] == 100.0
        assert s["mean"] == 100.0

    def test_percentiles(self):
        # 10 latencies from 10 to 100ms — p50 should be ~55, p95 ~95.5
        lat = [float(i) for i in range(10, 110, 10)]
        s = latency_summary(lat)
        assert s["n"] == 10
        assert 50 <= s["p50"] <= 60
        assert 90 <= s["p95"] <= 100
        assert s["mean"] == statistics_mean(lat)


def statistics_mean(xs: list[float]) -> float:
    """Tiny inline mean to avoid the import dance in this test."""
    return sum(xs) / len(xs)


class TestAggregateGraphragMetrics:
    def test_empty_input(self):
        m = aggregate_graphrag_metrics([])
        assert m["queries"] == 0
        assert m["latency"]["n"] == 0

    def test_aggregates_recall_and_latency(self):
        rows = [
            {
                "latency_ms": 100.0,
                "results": [{"retrieval_path": "graph", "chunk_id": "1"}],
                "retrieved_entities": ["Apple", "TSMC"],
                "expected_entities": ["Apple", "TSMC", "Samsung"],
            },
            {
                "latency_ms": 200.0,
                "results": [{"chunk_id": "1"}],
                "retrieved_entities": ["Apple"],
                "expected_entities": ["Apple", "TSMC"],
            },
        ]
        m = aggregate_graphrag_metrics(rows)
        assert m["queries"] == 2
        # Row 1: 2/3 recall, 100% graph hit; Row 2: 1/2 recall, 0% graph hit
        assert abs(m["entity_recall_mean"] - (2 / 3 + 1 / 2) / 2) < 1e-4
        assert m["graph_path_hit_rate_mean"] == 0.5
        assert m["latency"]["n"] == 2
        assert m["latency"]["p50"] == 150.0
        assert m["results_per_query_mean"] == 1.0
