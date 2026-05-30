"""Tests for authentication flow: register, login, token refresh, protected endpoints."""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timedelta


class TestTokenGeneration:
    """Test JWT token creation and validation."""

    def test_create_access_token_contains_claims(self):
        from src.auth.jwt_handler import create_access_token, decode_access_token
        token = create_access_token({"sub": "user1", "company_id": "comp1"})
        payload = decode_access_token(token)
        assert payload["sub"] == "user1"
        assert payload["company_id"] == "comp1"
        assert payload["type"] == "access"
        assert "exp" in payload

    def test_create_refresh_token_has_refresh_type(self):
        from src.auth.jwt_handler import create_refresh_token, verify_token
        token = create_refresh_token({"sub": "user1", "token_id": "tok1"})
        payload = verify_token(token)
        assert payload["type"] == "refresh"
        assert payload["sub"] == "user1"

    def test_expired_token_raises(self):
        from src.auth.jwt_handler import create_access_token, decode_access_token
        import jwt as pyjwt
        token = create_access_token(
            {"sub": "user1"},
            expires_delta=timedelta(seconds=-1),
        )
        with pytest.raises(pyjwt.InvalidTokenError):
            decode_access_token(token)


class TestRegisterEndpoint:
    """Test POST /api/auth/register."""

    @patch("src.api.auth.get_db_session")
    @patch("src.api.auth._generate_id", return_value="new-user-id")
    def test_register_success(self, mock_gen_id, mock_db_session, client):
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
        mock_db_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_db_session.return_value.__aexit__ = AsyncMock(return_value=False)

        resp = client.post("/api/auth/register", json={
            "email": "test@example.com",
            "password": "SecurePass123!",
            "company_name": "Test Co",
        })
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["user"]["email"] == "test@example.com"

    def test_register_rejects_short_password(self, client):
        """Password shorter than 8 chars should be rejected by pydantic."""
        resp = client.post("/api/auth/register", json={
            "email": "test@example.com",
            "password": "short",
        })
        assert resp.status_code == 422

    def test_register_rejects_missing_fields(self, client):
        resp = client.post("/api/auth/register", json={})
        assert resp.status_code == 422


class TestLoginEndpoint:
    """Test POST /api/auth/login."""

    @patch("src.api.auth.get_db_session")
    def test_login_with_wrong_password_returns_401(self, mock_db_session, client):
        from src.auth.password import hash_password
        mock_user = MagicMock()
        mock_user.id = "user1"
        mock_user.email = "test@example.com"
        mock_user.password_hash = hash_password("correct-password")
        mock_user.is_active = True
        mock_user.role = "admin"
        mock_user.company_id = "comp1"

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_db_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_db_session.return_value.__aexit__ = AsyncMock(return_value=False)

        resp = client.post("/api/auth/login", json={
            "email": "test@example.com",
            "password": "wrong-password",
        })
        assert resp.status_code == 401

    def test_login_rejects_empty_body(self, client):
        resp = client.post("/api/auth/login", json={})
        assert resp.status_code == 422


class TestProtectedEndpoints:
    """Test that protected endpoints require authentication."""

    def test_query_requires_auth(self, client):
        resp = client.post("/api/query", json={"query": "test"})
        assert resp.status_code in (401, 403)

    def test_stats_requires_auth(self, client):
        resp = client.get("/api/stats")
        assert resp.status_code in (401, 403)

    def test_ingest_trigger_requires_auth(self, client):
        resp = client.post("/api/ingest/trigger", json={})
        assert resp.status_code in (401, 403)

    def test_health_does_not_require_auth(self, client):
        """Health endpoints should be publicly accessible."""
        resp = client.get("/api/health")
        assert resp.status_code != 401


class TestTokenRefresh:
    """Test POST /api/auth/refresh."""

    def test_refresh_without_token_returns_422(self, client):
        resp = client.post("/api/auth/refresh", json={})
        assert resp.status_code == 422

    @patch("src.api.auth.get_db_session")
    def test_refresh_with_invalid_token_returns_401(self, mock_db_session, client):
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
        mock_db_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_db_session.return_value.__aexit__ = AsyncMock(return_value=False)

        resp = client.post("/api/auth/refresh", json={
            "refresh_token": "invalid-token",
        })
        assert resp.status_code == 401


class TestPasswordHashing:
    """Test password hashing utilities."""

    def test_hash_and_verify(self):
        from src.auth.password import hash_password, verify_password
        pw = "MySecurePass123!"
        hashed = hash_password(pw)
        assert verify_password(pw, hashed)
        assert not verify_password("wrong", hashed)

    def test_different_passwords_different_hashes(self):
        from src.auth.password import hash_password
        h1 = hash_password("password1")
        h2 = hash_password("password2")
        assert h1 != h2
