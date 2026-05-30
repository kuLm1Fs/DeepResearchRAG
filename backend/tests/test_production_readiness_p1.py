import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.vectorstore.milvus_store import (
    compute_content_hash,
    create_schema,
    filter_new_records_by_hash,
)


class MilvusMetadataSchemaTests(unittest.TestCase):
    def test_schema_includes_production_citation_and_tenant_metadata(self):
        schema = create_schema()
        fields = {field.name for field in schema.fields}

        self.assertIn("url", fields)
        self.assertIn("author", fields)
        self.assertIn("external_id", fields)
        self.assertIn("fetched_at", fields)
        self.assertIn("chunk_id", fields)
        self.assertIn("parent_doc_id", fields)
        self.assertIn("user_id", fields)
        self.assertIn("company_id", fields)


class ContentHashDedupTests(unittest.TestCase):
    def test_compute_content_hash_is_stable_for_same_title_and_content(self):
        left = compute_content_hash({"title": "AI News", "content": "New model released"})
        right = compute_content_hash({"title": "AI News", "content": "New model released"})

        self.assertEqual(left, right)

    def test_filter_new_records_by_hash_removes_existing_and_batch_duplicates(self):
        existing_hash = compute_content_hash({"title": "Existing", "content": "Already stored"})
        records = [
            {"title": "Existing", "content": "Already stored"},
            {"title": "Fresh", "content": "New item"},
            {"title": "Fresh", "content": "New item"},
        ]

        filtered = filter_new_records_by_hash(records, {existing_hash})

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["title"], "Fresh")
        self.assertIn("content_hash", filtered[0])


class HealthReadinessTests(unittest.TestCase):
    def test_livez_reports_process_alive_without_dependency_checks(self):
        response = TestClient(create_app()).get("/api/livez")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "alive")

    def test_health_reports_postgres_and_milvus_readiness(self):
        app = create_app()

        class FakeStore:
            def count(self):
                return 1

        async def fake_check_connection():
            return True

        with (
            patch("src.api.routes.MilvusStore", return_value=FakeStore()),
            patch("src.api.routes.check_connection", side_effect=fake_check_connection),
        ):
            response = TestClient(app).get("/api/health")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "healthy")
        self.assertTrue(data["milvus_connected"])
        self.assertTrue(data["postgres_connected"])

    def test_readyz_reuses_dependency_readiness(self):
        app = create_app()

        class FakeStore:
            def count(self):
                return 1

        async def fake_check_connection():
            return True

        with (
            patch("src.api.routes.MilvusStore", return_value=FakeStore()),
            patch("src.api.routes.check_connection", side_effect=fake_check_connection),
        ):
            response = TestClient(app).get("/api/readyz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "healthy")
