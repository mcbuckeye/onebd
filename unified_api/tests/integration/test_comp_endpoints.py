"""
TDD: Comp builder endpoint tests — write these FIRST, then implement.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from unified_api.main import app
    with TestClient(app) as c:
        yield c


class TestCompBuildEndpoint:
    """Test POST /api/comps/build"""

    def test_build_comps_returns_200(self, client):
        resp = client.post("/api/comps/build", json={
            "indication": "Oncology",
            "phase": "Phase 2",
        })
        assert resp.status_code == 200

    def test_build_comps_response_structure(self, client):
        data = client.post("/api/comps/build", json={
            "indication": "Oncology",
        }).json()
        assert "deals" in data
        assert "stats" in data
        assert isinstance(data["deals"], list)
        assert "count" in data["stats"]

    def test_build_comps_deals_have_scores(self, client):
        data = client.post("/api/comps/build", json={
            "indication": "Oncology",
            "phase": "Phase 2",
        }).json()
        if len(data["deals"]) > 0:
            assert "match_score" in data["deals"][0]
            assert 0 <= data["deals"][0]["match_score"] <= 1

    def test_build_comps_sorted_by_score(self, client):
        data = client.post("/api/comps/build", json={
            "indication": "Oncology",

        }).json()
        if len(data["deals"]) > 1:
            scores = [d["match_score"] for d in data["deals"]]
            assert scores == sorted(scores, reverse=True)

    def test_build_comps_limits_results(self, client):
        data = client.post("/api/comps/build", json={
            "indication": "Oncology",
            "limit": 5,
        }).json()
        assert len(data["deals"]) <= 5


class TestCompSaveEndpoint:
    """Test comp set save/retrieve."""

    def test_save_comp_set(self, client):
        resp = client.post("/api/comps", json={
            "name": "Test Comp Set",
            "deal_ids": [1, 2, 3],
            "criteria": {"indication": "Oncology"},
        })
        # May be 200 or 201
        assert resp.status_code in [200, 201]

    def test_list_comp_sets(self, client):
        resp = client.get("/api/comps")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list) or "comp_sets" in resp.json()
