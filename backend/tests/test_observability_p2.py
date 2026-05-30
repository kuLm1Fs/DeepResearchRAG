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


class MetricsEndpointTests(unittest.TestCase):
    def test_metrics_endpoint_returns_text_payload(self):
        response = TestClient(create_app()).get("/api/metrics")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/plain", response.headers["content-type"])
        self.assertIn("rag_app_info", response.text)

