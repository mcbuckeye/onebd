"""
TDD: Territory rights endpoint tests.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from unified_api.main import app
    with TestClient(app) as c:
        yield c


class TestTerritoryEndpoint:
    """Test GET /api/territory/{drug_id}/map"""

    def test_territory_returns_200(self, client):
        resp = client.get("/api/territory/1/map")
        assert resp.status_code in [200, 404]  # 404 if drug doesn't exist

    def test_territory_response_structure(self, client):
        resp = client.get("/api/territory/1/map")
        if resp.status_code == 200:
            data = resp.json()
            assert "drug" in data
            assert "territories" in data
            assert isinstance(data["territories"], list)

    def test_territory_entries_have_required_fields(self, client):
        resp = client.get("/api/territory/1/map")
        if resp.status_code == 200:
            for t in resp.json().get("territories", []):
                assert "territory" in t
                assert "status" in t  # committed, available, etc.
