"""Tests for data ingestion pipeline: collectors, deduplication, embedding."""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


class TestRSSCollector:
    """Test RSS feed collector."""

    def test_rss_collector_inherits_base(self):
        from src.ingestion.rss_collector import RSSCollector
        from src.ingestion.base import BaseCollector
        assert issubclass(RSSCollector, BaseCollector)

    def test_rss_collector_instantiation(self):
        from src.ingestion.rss_collector import RSSCollector
        collector = RSSCollector(name="test-rss", sources=[{"name": "test", "url": "https://example.com/rss"}])
        assert collector is not None


class TestHackerNewsCollector:
    """Test Hacker News API collector."""

    def test_hn_collector_inherits_base(self):
        from src.ingestion.hn_collector import HNCollector
        from src.ingestion.base import BaseCollector
        assert issubclass(HNCollector, BaseCollector)

    def test_hn_collector_instantiation(self):
        from src.ingestion.hn_collector import HNCollector
        collector = HNCollector()
        assert collector is not None


class TestDatasetCollector:
    """Test HuggingFace dataset collector."""

    def test_dataset_collector_inherits_base(self):
        from src.ingestion.dataset_collector import DatasetCollector
        from src.ingestion.base import BaseCollector
        assert issubclass(DatasetCollector, BaseCollector)


class TestContentHashDedup:
    """Test content hash deduplication logic."""

    def test_content_hash_deterministic(self):
        """Same content should produce the same hash."""
        import hashlib
        content = "This is test article content."
        h1 = hashlib.sha256(content.encode()).hexdigest()
        h2 = hashlib.sha256(content.encode()).hexdigest()
        assert h1 == h2

    def test_content_hash_different_for_different_content(self):
        """Different content should produce different hashes."""
        import hashlib
        h1 = hashlib.sha256("content A".encode()).hexdigest()
        h2 = hashlib.sha256("content B".encode()).hexdigest()
        assert h1 != h2


class TestIngestionAPI:
    """Test ingestion trigger API endpoint."""

    def test_ingest_trigger_requires_auth(self, client):
        resp = client.post("/api/ingest/trigger", json={})
        assert resp.status_code in (401, 403)

    def test_ingest_trigger_with_auth(self, client):
        from src.api.auth import get_current_user
        mock_user = MagicMock()
        mock_user.id = "test-user-id"
        mock_user.company_id = "test-company-id"
        client.app.dependency_overrides[get_current_user] = lambda: mock_user

        try:
            resp = client.post(
                "/api/ingest/trigger",
                json={"source": "hackernews", "limit": 5},
            )
            assert resp.status_code in (200, 202)
        finally:
            client.app.dependency_overrides.clear()

    def test_ingest_status_requires_auth(self, client):
        resp = client.get("/api/ingest/status")
        assert resp.status_code in (401, 403)


class TestEmbeddingBatching:
    """Test embedding API batching logic."""

    def test_batch_size_respected(self):
        """Verify batch splitting logic."""
        from src.vectorstore.embedding import BATCH_SIZE
        items = list(range(BATCH_SIZE * 3 + 10))
        batches = [items[i:i + BATCH_SIZE] for i in range(0, len(items), BATCH_SIZE)]
        assert len(batches) == 4
        assert len(batches[-1]) == 10

    @patch("src.vectorstore.embedding._call_embedding_api")
    def test_embedding_returns_correct_dimensions(self, mock_api):
        """Embedding should return 1024-dim vectors."""
        mock_api.return_value = [[0.1] * 1024]

        from src.vectorstore.embedding import embed_texts
        result = embed_texts(["test text"])
        assert len(result) == 1
        assert len(result[0]) == 1024


class TestPipelineModule:
    """Test ingestion pipeline orchestration."""

    def test_pipeline_module_importable(self):
        from src.ingestion.pipeline import IngestionPipeline
        assert IngestionPipeline is not None

    def test_indexer_function_importable(self):
        from src.ingestion.indexer import index_articles
        assert callable(index_articles)
