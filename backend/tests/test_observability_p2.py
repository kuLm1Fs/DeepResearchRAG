import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.core.metrics import MetricsRegistry


class MetricsRegistryTests(unittest.TestCase):
    def test_counter_rendering_uses_prometheus_text_format(self):
        registry = MetricsRegistry()
        registry.increment("rag_query_requests_total")
        registry.increment("rag_query_requests_total", amount=2)

        rendered = registry.render_prometheus()

        self.assertIn("# TYPE rag_query_requests_total counter", rendered)
        self.assertIn("rag_query_requests_total 3", rendered)

    def test_counter_rendering_supports_low_cardinality_labels(self):
        registry = MetricsRegistry()
        registry.increment(
            "rag_query_requests_total",
            labels={"route": "/api/query", "status": "success"},
        )

        rendered = registry.render_prometheus()

        self.assertIn(
            'rag_query_requests_total{route="/api/query",status="success"} 1',
            rendered,
        )

    def test_histogram_rendering_uses_prometheus_bucket_format(self):
        registry = MetricsRegistry()
        registry.observe(
            "rag_llm_latency_seconds",
            0.7,
            labels={"provider": "deepseek", "operation": "chat"},
            buckets=(0.1, 0.5, 1.0),
        )
        registry.observe(
            "rag_llm_latency_seconds",
            1.2,
            labels={"provider": "deepseek", "operation": "chat"},
            buckets=(0.1, 0.5, 1.0),
        )

        rendered = registry.render_prometheus()

        self.assertIn("# TYPE rag_llm_latency_seconds histogram", rendered)
        self.assertIn(
            'rag_llm_latency_seconds_bucket{operation="chat",provider="deepseek",le="0.5"} 0',
            rendered,
        )
        self.assertIn(
            'rag_llm_latency_seconds_bucket{operation="chat",provider="deepseek",le="1.0"} 1',
            rendered,
        )
        self.assertIn(
            'rag_llm_latency_seconds_bucket{operation="chat",provider="deepseek",le="+Inf"} 2',
            rendered,
        )
        self.assertIn(
            'rag_llm_latency_seconds_count{operation="chat",provider="deepseek"} 2',
            rendered,
        )

    def test_gauge_rendering_tracks_latest_value(self):
        registry = MetricsRegistry()
        registry.set_gauge("rag_research_tasks_inflight", 3, labels={"status": "running"})
        registry.set_gauge("rag_research_tasks_inflight", 2, labels={"status": "running"})

        rendered = registry.render_prometheus()

        self.assertIn("# TYPE rag_research_tasks_inflight gauge", rendered)
        self.assertIn('rag_research_tasks_inflight{status="running"} 2', rendered)


class MetricsEndpointTests(unittest.TestCase):
    def test_metrics_endpoint_returns_text_payload(self):
        response = TestClient(create_app()).get("/api/metrics")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/plain", response.headers["content-type"])
        self.assertIn("rag_app_info", response.text)
