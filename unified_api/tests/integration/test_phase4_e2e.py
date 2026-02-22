"""
End-to-end integration tests for Phase 4.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from unified_api.main import app
    with TestClient(app) as c:
        yield c


class TestPhase4Endpoints:

    def test_data_health(self, client):
        resp = client.get("/api/health/data")
        assert resp.status_code == 200
        data = resp.json()
        assert "overall_score" in data
        assert "sources" in data

    def test_enrichment_status(self, client):
        resp = client.get("/api/enrichment/status")
        assert resp.status_code == 200

    def test_parse_financials_dry_run(self, client):
        resp = client.post("/api/enrichment/parse-financials?dry_run=true&batch_size=5")
        assert resp.status_code == 200
        assert resp.json()["dry_run"] is True

    def test_all_routers_registered(self, client):
        """Verify all expected routes exist."""
        resp = client.get("/openapi.json")
        paths = resp.json()["paths"]
        expected = [
            "/api/health", "/api/health/data",
            "/api/auth/login", "/api/auth/register",
            "/api/dashboard/executive",
            "/api/chat/v2",
            "/api/comps/build",
            "/api/dd/generate",
            "/api/briefings/generate",
            "/api/recommendations",
            "/api/enrichment/status",
        ]
        for path in expected:
            assert path in paths, f"Missing route: {path}"

    def test_timing_header(self, client):
        resp = client.get("/api/health")
        assert "x-response-time" in resp.headers
