"""
TDD: Data health endpoint tests.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from unified_api.main import app
    with TestClient(app) as c:
        yield c


class TestDataHealthEndpoint:

    def test_health_data_returns_200(self, client):
        resp = client.get("/api/health/data")
        assert resp.status_code == 200

    def test_health_data_response_structure(self, client):
        data = client.get("/api/health/data").json()
        assert "overall_score" in data
        assert "checks" in data
        assert "sources" in data
        assert isinstance(data["checks"], list)

    def test_health_data_sources_include_all(self, client):
        sources = client.get("/api/health/data").json()["sources"]
        # Should report on all data sources
        assert "cortellis_deals" in sources
        assert "companies" in sources

    def test_health_data_checks_have_name_and_status(self, client):
        checks = client.get("/api/health/data").json()["checks"]
        for check in checks:
            assert "name" in check
            assert "status" in check
            assert check["status"] in ("ok", "warning", "critical")
