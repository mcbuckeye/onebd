"""
End-to-end integration tests for Phase 3.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from unified_api.main import app
    with TestClient(app) as c:
        yield c


class TestPhase3Endpoints:

    def test_dd_generate(self, client):
        resp = client.post("/api/dd/generate", json={"company_id": 1})
        assert resp.status_code in [200, 404]

    def test_territory_map(self, client):
        resp = client.get("/api/territory/1/map")
        assert resp.status_code in [200, 404]

    def test_briefing_generate(self, client):
        resp = client.post("/api/briefings/generate", json={"topic": "oncology"})
        assert resp.status_code == 200
        data = resp.json()
        assert "title" in data
        assert "sections" in data

    def test_briefing_list(self, client):
        resp = client.get("/api/briefings")
        assert resp.status_code == 200

    def test_recommendations(self, client):
        resp = client.get("/api/recommendations")
        assert resp.status_code == 200
        data = resp.json()
        assert "recommendations" in data

    def test_recommendations_have_reasons(self, client):
        data = client.get("/api/recommendations").json()
        for rec in data["recommendations"]:
            assert "reasons" in rec
            assert isinstance(rec["reasons"], list)
