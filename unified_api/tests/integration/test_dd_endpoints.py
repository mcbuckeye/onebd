"""
TDD: DD Package endpoint tests.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from unified_api.main import app
    with TestClient(app) as c:
        yield c


class TestDDGenerateEndpoint:
    """Test POST /api/dd/generate"""

    def test_generate_dd_returns_200(self, client):
        resp = client.post("/api/dd/generate", json={"company_id": 1})
        assert resp.status_code == 200

    def test_generate_dd_response_structure(self, client):
        data = client.post("/api/dd/generate", json={"company_id": 1}).json()
        assert "company" in data
        assert "sections" in data
        assert isinstance(data["sections"], list)
        assert len(data["sections"]) > 0

    def test_generate_dd_sections_have_titles(self, client):
        data = client.post("/api/dd/generate", json={"company_id": 1}).json()
        for section in data["sections"]:
            assert "title" in section

    def test_generate_dd_has_risk_flags(self, client):
        data = client.post("/api/dd/generate", json={"company_id": 1}).json()
        assert "risk_flags" in data
        assert isinstance(data["risk_flags"], list)

    def test_generate_dd_invalid_company(self, client):
        resp = client.post("/api/dd/generate", json={"company_id": 999999})
        # Should still return 200 with empty/minimal data, not crash
        assert resp.status_code in [200, 404]
