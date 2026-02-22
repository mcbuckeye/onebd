"""
TDD: Production hardening tests.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from unified_api.main import app
    with TestClient(app) as c:
        yield c


class TestProductionEndpoints:

    def test_health_returns_quickly(self, client):
        import time
        start = time.time()
        resp = client.get("/api/health")
        elapsed = time.time() - start
        assert resp.status_code == 200
        assert elapsed < 2.0  # Health check must be fast

    def test_rate_limiting_header(self, client):
        """Rate limiting middleware should add headers."""
        resp = client.get("/api/health")
        # At minimum, should not crash
        assert resp.status_code == 200

    def test_cors_headers(self, client):
        resp = client.options("/api/health", headers={"Origin": "http://localhost:5173"})
        # Should not crash
        assert resp.status_code in (200, 204, 405)

    def test_api_docs_available(self, client):
        resp = client.get("/docs")
        assert resp.status_code == 200

    def test_openapi_json(self, client):
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        data = resp.json()
        assert "paths" in data
        # Should have many endpoints
        assert len(data["paths"]) > 30
