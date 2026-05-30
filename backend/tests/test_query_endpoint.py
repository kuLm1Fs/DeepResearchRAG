"""Tests for POST /api/query SSE streaming endpoint."""
import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


class TestQueryEndpoint:
    """Test query endpoint with mocked dependencies."""

    def _override_auth(self, client):
        """Override get_current_user dependency to return a mock user."""
        from src.api.auth import get_current_user
        mock_user = MagicMock()
        mock_user.id = "test-user-id"
        mock_user.company_id = "test-company-id"
        mock_user.role = "admin"
        client.app.dependency_overrides[get_current_user] = lambda: mock_user
        return mock_user

    def _clear_overrides(self, client):
        client.app.dependency_overrides.clear()

    def test_query_returns_sse_stream(self, client):
        """Query with stream=true should return SSE events."""
        self._override_auth(client)
        try:
            resp = client.post(
                "/api/query",
                json={"query": "What is AI?", "stream": True},
            )
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers.get("content-type", "")
        finally:
            self._clear_overrides(client)

    def test_query_without_auth_returns_error(self, client):
        """Query without auth should be rejected."""
        resp = client.post("/api/query", json={"query": "test"})
        assert resp.status_code in (401, 403)

    def test_query_validates_empty_query(self, client):
        """Empty query should be rejected."""
        self._override_auth(client)
        try:
            resp = client.post(
                "/api/query",
                json={"query": ""},
            )
            assert resp.status_code in (400, 422)
        finally:
            self._clear_overrides(client)

    def test_query_rejects_missing_body(self, client):
        """Missing request body should return 422."""
        self._override_auth(client)
        try:
            resp = client.post("/api/query")
            assert resp.status_code == 422
        finally:
            self._clear_overrides(client)


class TestQuerySSEFormat:
    """Test SSE event format from query endpoint."""

    def _parse_sse_events(self, body: str) -> list[dict]:
        """Parse SSE text body into list of event dicts."""
        events = []
        for line in body.strip().split("\n"):
            if line.startswith("data: "):
                try:
                    events.append(json.loads(line[6:]))
                except json.JSONDecodeError:
                    pass
        return events

    def test_sse_stream_returns_valid_events(self, client):
        """SSE stream should return parseable SSE events."""
        from src.api.auth import get_current_user
        mock_user = MagicMock()
        mock_user.id = "test-user-id"
        mock_user.company_id = "test-company-id"
        client.app.dependency_overrides[get_current_user] = lambda: mock_user

        try:
            with patch("agent.graph.run_agent_stream") as mock_agent:
                async def fake_stream(*args, **kwargs):
                    yield {"type": "sources", "data": []}
                    yield {"type": "token", "data": "Hello"}
                    yield {"type": "done", "data": {"answer": "Hello"}}

                mock_agent.side_effect = fake_stream

                resp = client.post(
                    "/api/query",
                    json={"query": "test query", "stream": True},
                )
                assert resp.status_code == 200
                assert "text/event-stream" in resp.headers.get("content-type", "")

                events = self._parse_sse_events(resp.text)
                assert len(events) > 0
        finally:
            client.app.dependency_overrides.clear()


class TestHealthEndpoint:
    """Test health check endpoints."""

    def test_health_endpoint_accessible(self, client):
        resp = client.get("/api/health")
        assert resp.status_code in (200, 503)

    def test_livez_endpoint(self, client):
        resp = client.get("/api/livez")
        assert resp.status_code == 200


class TestStatsEndpoint:
    """Test GET /api/stats."""

    def test_stats_requires_auth(self, client):
        resp = client.get("/api/stats")
        assert resp.status_code in (401, 403)

    def test_stats_returns_data(self, client):
        from src.api.auth import get_current_user
        mock_user = MagicMock()
        mock_user.id = "test-user-id"
        mock_user.company_id = "test-company-id"
        client.app.dependency_overrides[get_current_user] = lambda: mock_user

        try:
            with patch("src.api.routes.MilvusStore") as MockStore:
                mock_instance = MagicMock()
                mock_instance.query.return_value = [
                    {"source": "test", "category": "technology"},
                    {"source": "test", "category": "science"},
                ]
                MockStore.return_value = mock_instance

                resp = client.get("/api/stats")
                assert resp.status_code == 200
                data = resp.json()
                assert "total_articles" in data
        finally:
            client.app.dependency_overrides.clear()
