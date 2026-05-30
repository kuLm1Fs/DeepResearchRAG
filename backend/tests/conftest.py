"""Shared test fixtures for RAG News Intelligence backend tests."""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Ensure src is importable (same as existing tests)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture(autouse=True)
def _test_env(monkeypatch):
    """Set test-safe environment variables before each test."""
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-for-testing-only-32chars!")
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("VOLCENGINE_API_KEY", "test-key")
    monkeypatch.setenv("MILVUS_HOST", "localhost")
    monkeypatch.setenv("MILVUS_PORT", "19530")
    monkeypatch.setenv("POSTGRES_HOST", "localhost")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_DB", "rag_news_test")
    monkeypatch.setenv("POSTGRES_USER", "rag_test")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test_pass")

    # Patch settings singleton directly (env vars are read at import time)
    from src.core.config import settings
    settings.jwt_secret = "test-secret-key-for-testing-only-32chars!"


@pytest.fixture
def client():
    """FastAPI TestClient with mocked external dependencies."""
    with patch("src.vectorstore.milvus_store.get_milvus_connection"):
        from src.api.app import create_app
        from fastapi.testclient import TestClient
        return TestClient(create_app())


@pytest.fixture
def auth_headers(client):
    """Generate valid JWT auth headers for testing.

    Depends on client to ensure the app (and thus settings) is initialized first.
    """
    from src.auth.jwt_handler import create_access_token
    token = create_access_token({"sub": "test-user-id", "company_id": "test-company-id"})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def mock_embedding():
    """Mock embedding API to return fixed 1024-dim vectors."""
    def _embed(texts, **kwargs):
        return [[0.1] * 1024 for _ in texts]

    with patch("src.vectorstore.embedding.embed_texts", side_effect=_embed) as m:
        yield m


@pytest.fixture
def mock_llm():
    """Mock LLM to return a fixed response."""
    mock_response = MagicMock()
    mock_response.content = "This is a test answer from the LLM."
    mock_response.usage = MagicMock(total_tokens=100)

    mock_llm_instance = MagicMock()
    mock_llm_instance.invoke.return_value = mock_response
    mock_llm_instance.ainvoke.return_value = mock_response

    with patch("src.agent.nodes.create_llm", return_value=mock_llm_instance):
        yield mock_llm_instance


@pytest.fixture
def mock_milvus():
    """Mock Milvus connection for vector store operations."""
    with patch("src.vectorstore.milvus_store.get_milvus_connection"):
        yield MagicMock()
