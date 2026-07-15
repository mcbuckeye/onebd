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
        assert result["content"]["matching_deals"] == 100

    def test_build_competitor_summary_returns_dict(self):
        from unified_api.services.briefing_generator import build_competitor_summary
        result = build_competitor_summary([{"name": "Pfizer", "deals": 5}])
        assert isinstance(result, dict)
        assert "title" in result

    def test_build_notable_deals_returns_dict(self):
        from unified_api.services.briefing_generator import build_notable_deals
        result = build_notable_deals([{"title": "Test Deal", "value": 100}])
        assert isinstance(result, dict)

    @pytest.mark.parametrize(
        ("topic", "expected"),
        [
            ("ADC deals", "ADC"),
            ("M&A activity", "M&A"),
            ("Hanchor Bio", "Hanchor Bio"),
        ],
    )
    def test_briefing_topic_removes_only_generic_ui_suffixes(self, topic, expected):
        from unified_api.routers.briefings import _search_topic

        assert _search_topic(topic) == expected
