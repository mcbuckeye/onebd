"""
TDD: Briefing generator tests.
"""
import pytest


class TestBriefingSections:
    """Test briefing section generation."""

    def test_build_market_summary_returns_dict(self):
        from unified_api.services.briefing_generator import build_market_summary
        result = build_market_summary({"deals_30d": 100, "top_therapy": "Oncology"})
        assert isinstance(result, dict)
        assert "title" in result
        assert "content" in result

    def test_build_competitor_summary_returns_dict(self):
        from unified_api.services.briefing_generator import build_competitor_summary
        result = build_competitor_summary([{"name": "Pfizer", "deals": 5}])
        assert isinstance(result, dict)
        assert "title" in result

    def test_build_notable_deals_returns_dict(self):
        from unified_api.services.briefing_generator import build_notable_deals
        result = build_notable_deals([{"title": "Test Deal", "value": 100}])
        assert isinstance(result, dict)
