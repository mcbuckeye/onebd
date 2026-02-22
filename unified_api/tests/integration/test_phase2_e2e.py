"""
End-to-end integration tests for Phase 2.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from unified_api.main import app
    with TestClient(app) as c:
        yield c


class TestPhase2Endpoints:
    """Verify all Phase 2 endpoints exist and return valid responses."""

    def test_market_trends(self, client):
        resp = client.get("/api/analytics/market-trends")
        assert resp.status_code == 200

    def test_valuations_by_phase(self, client):
        resp = client.get("/api/analytics/valuations/by-phase")
        assert resp.status_code == 200

    def test_valuations_by_indication(self, client):
        resp = client.get("/api/analytics/valuations/by-indication")
        assert resp.status_code == 200

    def test_geographic_distribution(self, client):
        resp = client.get("/api/analytics/geographic-distribution")
        assert resp.status_code == 200

    def test_top_acquirers(self, client):
        resp = client.get("/api/analytics/top-acquirers")
        assert resp.status_code == 200

    def test_top_deals(self, client):
        resp = client.get("/api/analytics/top-deals")
        assert resp.status_code == 200

    def test_therapy_area_heatmap(self, client):
        resp = client.get("/api/analytics/therapy-area-heatmap")
        assert resp.status_code == 200

    def test_yoy_growth(self, client):
        resp = client.get("/api/analytics/yoy-growth")
        assert resp.status_code == 200

    def test_partnership_network(self, client):
        resp = client.get("/api/graph/industry-network?limit=10")
        assert resp.status_code == 200

    def test_comp_build(self, client):
        resp = client.post("/api/comps/build", json={"indication": "Oncology", "limit": 5})
        assert resp.status_code == 200
        data = resp.json()
        assert "deals" in data
        assert "stats" in data

    def test_comp_list(self, client):
        resp = client.get("/api/comps")
        assert resp.status_code == 200

    def test_contract_search(self, client):
        resp = client.get("/api/search/contracts?query=royalty&mode=fulltext&limit=5")
        assert resp.status_code == 200
