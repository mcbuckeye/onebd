"""
TDD: Briefing endpoint tests.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from unified_api.main import app
    with TestClient(app) as c:
        yield c


class TestBriefingGenerate:
    """Test POST /api/briefings/generate"""

    def test_generate_returns_200(self, client):
        resp = client.post("/api/briefings/generate", json={"topic": "oncology"})
        assert resp.status_code == 200

    def test_generate_response_structure(self, client):
        data = client.post("/api/briefings/generate", json={"topic": "oncology"}).json()
        assert "title" in data
        assert "sections" in data
        assert isinstance(data["sections"], list)

    def test_generate_with_company_topic(self, client):
        data = client.post("/api/briefings/generate", json={"topic": "Pfizer"}).json()
        assert "title" in data

    def test_list_briefings(self, client):
        resp = client.get("/api/briefings")
        assert resp.status_code == 200
