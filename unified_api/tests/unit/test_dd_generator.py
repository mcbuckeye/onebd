"""
TDD: Due Diligence package generator tests.
"""
import pytest


class TestDDPackageStructure:
    """Test DD package generation logic."""

    def test_package_has_required_sections(self):
        from unified_api.services.dd_generator import DD_SECTIONS
        required = ["company_overview", "deal_history", "drug_portfolio", "partnerships", "financials"]
        for section in required:
            assert section in DD_SECTIONS

    def test_build_company_overview_returns_dict(self):
        from unified_api.services.dd_generator import build_section
        # Mock data — function should handle gracefully
        result = build_section("company_overview", {"company_id": 1, "name": "Test Corp"})
        assert isinstance(result, dict)
        assert "title" in result
        assert "content" in result

    def test_build_section_unknown_type_returns_empty(self):
        from unified_api.services.dd_generator import build_section
        result = build_section("nonexistent_section", {})
        assert result["content"] is None or result["content"] == ""

    def test_risk_flags_detection(self):
        from unified_api.services.dd_generator import detect_risk_flags
        deal_data = {
            "terminated_deals": 5,
            "total_deals": 10,
            "concentrated_partnerships": True,
            "recent_litigation": True,
        }
        flags = detect_risk_flags(deal_data)
        assert isinstance(flags, list)
        assert len(flags) > 0
        assert all(isinstance(f, dict) and "flag" in f and "severity" in f for f in flags)

    def test_risk_flags_clean_company(self):
        from unified_api.services.dd_generator import detect_risk_flags
        clean_data = {
            "terminated_deals": 0,
            "total_deals": 50,
            "concentrated_partnerships": False,
            "recent_litigation": False,
        }
        flags = detect_risk_flags(clean_data)
        assert isinstance(flags, list)
        # Clean company may still have informational flags, but no high severity
        high_severity = [f for f in flags if f.get("severity") == "high"]
        assert len(high_severity) == 0
