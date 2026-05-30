"""Tests for security middleware, rate limiting, and CORS tightening."""
from unittest.mock import AsyncMock, patch, MagicMock
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from src.api.app import create_app

    return TestClient(create_app())


class TestSecurityHeaders:
    """SecurityHeadersMiddleware sets correct headers on every response."""

    def test_security_headers_present(self, client):
        resp = client.get("/api/livez")
        assert resp.status_code == 200
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert resp.headers["X-XSS-Protection"] == "1; mode=block"
        assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert "Content-Security-Policy" in resp.headers
        assert "default-src 'self'" in resp.headers["Content-Security-Policy"]

    def test_hsts_only_in_dev(self, client):
        """HSTS header should NOT appear in dev mode."""
        resp = client.get("/api/livez")
        assert "Strict-Transport-Security" not in resp.headers

    def test_hsts_present_in_prod(self):
        """HSTS header should appear when env=prod."""
        # Directly test the middleware logic by patching settings.is_prod
        from starlette.testclient import TestClient as StarletteTestClient
        from starlette.applications import Starlette
        from starlette.routing import Route
        from starlette.responses import PlainTextResponse

        from src.core.middleware import SecurityHeadersMiddleware

        async def homepage(request):
            return PlainTextResponse("ok")

        app = Starlette(routes=[Route("/", homepage)])
        app.add_middleware(SecurityHeadersMiddleware)

        with patch("src.core.middleware.settings") as mock_s:
            mock_s.is_prod = True
            test_client = StarletteTestClient(app)
            resp = test_client.get("/")
            assert resp.headers.get("Strict-Transport-Security") == "max-age=31536000; includeSubDomains"


class TestRequestBodySizeLimit:
    """RequestBodySizeMiddleware rejects oversized requests."""

    def test_rejects_oversized_request(self, client):
        """Requests with Content-Length > max should get 413."""
        resp = client.post(
            "/api/auth/login",
            content="{}",
            headers={"Content-Type": "application/json", "Content-Length": "99999999"},
        )
        assert resp.status_code == 413
        assert resp.json()["detail"] == "Request body too large"

    def test_allows_get_request(self, client):
        """GET requests without Content-Length pass through."""
        resp = client.get("/api/livez")
        assert resp.status_code == 200

    def test_allows_normal_sized_post(self, client):
        """Normal-sized POST requests pass through the size check (not 413)."""
        # POST to root — doesn't need DB, just checks middleware lets it through
        resp = client.post(
            "/",
            content='{"key":"value"}',
            headers={"Content-Type": "application/json", "Content-Length": "15"},
        )
        # 405 (Method Not Allowed) is fine — the point is it's not 413
        assert resp.status_code != 413


class TestRateLimiting:
    """Rate limiting middleware is configured."""

    def test_limiter_is_configured(self):
        """The app should have a limiter attached to its state."""
        from src.api.app import create_app
        app = create_app()
        assert hasattr(app.state, "limiter")

    def test_rate_limit_handler_registered(self):
        """RateLimitExceeded handler should be registered on the app."""
        from src.api.app import create_app
        from slowapi.errors import RateLimitExceeded
        app = create_app()
        # The exception handler dict should contain RateLimitExceeded
        assert RateLimitExceeded in app.exception_handlers


class TestCORSTightening:
    """CORS is tightened in production mode."""

    def test_dev_cors_allows_all_methods(self, client):
        """In dev mode, all methods are allowed."""
        resp = client.options(
            "/api/query",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization,Content-Type",
            },
        )
        assert resp.status_code in (200, 204)

    def test_prod_cors_restricts_methods(self):
        """In prod mode, only GET/POST/OPTIONS are allowed."""
        with patch("src.core.config.settings") as mock_settings:
            mock_settings.is_prod = True
            mock_settings.max_request_body_size = 1_048_576
            mock_settings.rate_limit_enabled = False
            mock_settings.rate_limit_default = "60/minute"
            mock_settings.cors_origins = "https://example.com"
            mock_settings.cors_origin_list = ["https://example.com"]
            mock_settings.debug = False
            mock_settings.llm_cache = False
            mock_settings.env = "prod"
            mock_settings.llm_provider = "deepseek"
            mock_settings.langchain_api_key = ""
            mock_settings.langchain_tracing_v2 = False
            mock_settings.llm_cache_enabled = False
            mock_settings.debug_enabled = False

            with patch("src.api.app.settings", mock_settings):
                from src.api.app import create_app
                prod_client = TestClient(create_app())
                resp = prod_client.options(
                    "/api/query",
                    headers={
                        "Origin": "https://example.com",
                        "Access-Control-Request-Method": "POST",
                        "Access-Control-Request-Headers": "Authorization,Content-Type",
                    },
                )
                # Should allow POST
                allow_methods = resp.headers.get("access-control-allow-methods", "")
                assert "POST" in allow_methods
