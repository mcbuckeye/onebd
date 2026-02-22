"""
End-to-end integration tests for Phase 1.
Verifies that all new features work together.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from unified_api.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def auth_headers(client):
    """Register a user and return auth headers."""
    resp = client.post("/api/auth/register", json={
        "email": "e2e_phase1@test.com",
        "password": "TestPass123!",
        "name": "E2E Test User",
    })
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestPhase1Endpoints:
    """Verify all Phase 1 endpoints exist and return valid responses."""

    def test_health(self, client):
        assert client.get("/health").status_code == 200

    def test_auth_flow(self, client, auth_headers):
        resp = client.get("/api/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["email"] == "e2e_phase1@test.com"

    def test_dashboard(self, client):
        resp = client.get("/api/dashboard/executive")
        assert resp.status_code == 200
        data = resp.json()
        assert "market_pulse" in data
        assert "notable_deals" in data

    def test_search_deals(self, client):
        resp = client.post("/api/search/deals", json={})
        assert resp.status_code == 200
        assert "total" in resp.json()
        assert "results" in resp.json()

    def test_search_deals_with_filters(self, client):
        resp = client.post("/api/search/deals?page=1&page_size=5", json={
            "therapy_area": "Oncology",
            "disclosed_only": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["page_size"] == 5

    def test_filter_options(self, client):
        resp = client.get("/api/search/filters")
        assert resp.status_code == 200
        data = resp.json()
        assert "therapy_areas" in data
        assert "deal_types" in data
        assert "phases" in data
        assert "statuses" in data
        assert len(data["therapy_areas"]) > 0

    def test_autocomplete_companies(self, client):
        resp = client.get("/api/search/autocomplete/companies?q=pfi")
        assert resp.status_code == 200
        assert "suggestions" in resp.json()

    def test_chat_v1_still_works(self, client):
        """Ensure original chat endpoint is not broken."""
        resp = client.post("/api/chat", json={"message": "SELECT COUNT(*) FROM deals", "mode": "sql"})
        assert resp.status_code == 200


class TestPhase1DataQuality:
    """Verify data integrity for dashboard and search."""

    def test_deals_table_has_data(self):
        from unified_api.services.database import get_cortellis_session
        from sqlalchemy import text
        
        with get_cortellis_session() as session:
            count = session.execute(text("SELECT COUNT(*) FROM deals")).scalar()
            assert count > 100000, f"Expected 100K+ deals, got {count}"

    def test_therapy_areas_populated(self):
        from unified_api.services.database import get_cortellis_session
        from sqlalchemy import text
        
        with get_cortellis_session() as session:
            count = session.execute(text("SELECT COUNT(*) FROM therapy_areas")).scalar()
            assert count > 0

    def test_finance_summary_exists(self):
        from unified_api.services.database import get_cortellis_session
        from sqlalchemy import text
        
        with get_cortellis_session() as session:
            count = session.execute(text(
                "SELECT COUNT(*) FROM deal_finance_summary WHERE total_projected_current_amount IS NOT NULL"
            )).scalar()
            assert count > 10000, f"Expected 10K+ deals with financial data, got {count}"
