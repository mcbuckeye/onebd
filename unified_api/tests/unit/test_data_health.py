"""
TDD: Data health check tests.
"""
import pytest


class TestDataHealthScoring:
    """Test data health scoring logic."""

    def test_score_returns_dict(self):
        from unified_api.services.data_health import compute_health_score
        result = compute_health_score({
            "deals_total": 145000,
            "deals_with_financials": 39000,
            "companies_total": 52000,
            "companies_with_xref": 692,
            "graph_companies": 55000,
            "graph_deals": 145000,
            "graph_relationships": 289000,
            "last_sync": "2026-07-15T06:30:00",
        })
        assert isinstance(result, dict)
        assert "overall_score" in result
        assert "checks" in result
        assert isinstance(result["checks"], list)

    def test_score_between_0_and_100(self):
        from unified_api.services.data_health import compute_health_score
        result = compute_health_score({
            "deals_total": 145000,
            "deals_with_financials": 39000,
            "companies_total": 52000,
            "companies_with_xref": 692,
            "graph_companies": 55000,
            "graph_deals": 145000,
            "graph_relationships": 289000,
            "last_sync": "2026-07-15T06:30:00",
        })
        assert 0 <= result["overall_score"] <= 100

    def test_stale_sync_flags_warning(self):
        from unified_api.services.data_health import compute_health_score
        result = compute_health_score({
            "deals_total": 145000,
            "deals_with_financials": 39000,
            "companies_total": 52000,
            "companies_with_xref": 692,
            "graph_companies": 55000,
            "graph_deals": 145000,
            "graph_relationships": 289000,
            "last_sync": "2026-01-01T00:00:00",  # Very stale
        })
        warnings = [c for c in result["checks"] if c["status"] == "warning" or c["status"] == "critical"]
        assert len(warnings) > 0

    def test_graph_mismatch_flags_warning(self):
        from unified_api.services.data_health import compute_health_score
        result = compute_health_score({
            "deals_total": 145000,
            "deals_with_financials": 39000,
            "companies_total": 52000,
            "companies_with_xref": 692,
            "graph_companies": 10000,  # Way fewer than PG
            "graph_deals": 50000,  # Way fewer than PG
            "graph_relationships": 100000,
            "last_sync": "2026-07-15T06:30:00",
        })
        warnings = [c for c in result["checks"] if c["status"] in ("warning", "critical")]
        assert len(warnings) > 0
