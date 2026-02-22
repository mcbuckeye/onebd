"""
TDD: Dashboard endpoint tests — write these FIRST, then implement.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from unified_api.main import app
    with TestClient(app) as c:
        yield c


class TestExecutiveDashboard:
    """Test GET /api/dashboard/executive"""

    def test_dashboard_returns_200(self, client):
        resp = client.get("/api/dashboard/executive")
        assert resp.status_code == 200

    def test_dashboard_has_market_pulse(self, client):
        data = client.get("/api/dashboard/executive").json()
        assert "market_pulse" in data
        pulse = data["market_pulse"]
        assert "deal_count_30d" in pulse
        assert "deal_count_prev_30d" in pulse
        assert "avg_value_30d" in pulse
        assert "top_therapy_areas" in pulse
        assert "monthly_trend" in pulse

    def test_dashboard_deal_counts_are_integers(self, client):
        pulse = client.get("/api/dashboard/executive").json()["market_pulse"]
        assert isinstance(pulse["deal_count_30d"], int)
        assert isinstance(pulse["deal_count_prev_30d"], int)
        assert pulse["deal_count_30d"] >= 0

    def test_dashboard_has_notable_deals(self, client):
        data = client.get("/api/dashboard/executive").json()
        assert "notable_deals" in data
        assert isinstance(data["notable_deals"], list)

    def test_notable_deals_have_required_fields(self, client):
        deals = client.get("/api/dashboard/executive").json()["notable_deals"]
        if len(deals) > 0:
            deal = deals[0]
            assert "id" in deal
            assert "title" in deal
            assert "date_start" in deal
            # total_value can be null

    def test_monthly_trend_ordered_chronologically(self, client):
        trend = client.get("/api/dashboard/executive").json()["market_pulse"]["monthly_trend"]
        if len(trend) > 1:
            months = [t["month"] for t in trend]
            assert months == sorted(months)

    def test_top_therapy_areas_limited(self, client):
        areas = client.get("/api/dashboard/executive").json()["market_pulse"]["top_therapy_areas"]
        assert len(areas) <= 5

    def test_top_therapy_areas_sorted_by_count(self, client):
        areas = client.get("/api/dashboard/executive").json()["market_pulse"]["top_therapy_areas"]
        if len(areas) > 1:
            counts = [a["count"] for a in areas]
            assert counts == sorted(counts, reverse=True)

    def test_dashboard_is_cached_on_second_call(self, client):
        """Second call should be faster (cached). Just verify it returns same data."""
        resp1 = client.get("/api/dashboard/executive").json()
        resp2 = client.get("/api/dashboard/executive").json()
        assert resp1["market_pulse"]["deal_count_30d"] == resp2["market_pulse"]["deal_count_30d"]
