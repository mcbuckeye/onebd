"""
TDD: Comp builder tests — write these FIRST, then implement.
"""
import pytest


class TestCompMatchScoring:
    """Test deal similarity scoring for comp building."""

    def test_exact_match_scores_high(self):
        from unified_api.services.comp_builder import score_deal_similarity
        criteria = {"indication": "NSCLC", "phase": "Phase 2", "modality": "ADC"}
        deal = {"indication": "NSCLC", "phase": "Phase 2", "modality": "ADC"}
        score = score_deal_similarity(criteria, deal)
        assert score >= 0.8

    def test_no_match_scores_low(self):
        from unified_api.services.comp_builder import score_deal_similarity
        criteria = {"indication": "NSCLC", "phase": "Phase 2", "modality": "ADC"}
        deal = {"indication": "Diabetes", "phase": "Approved", "modality": "Small molecule"}
        score = score_deal_similarity(criteria, deal)
        assert score < 0.3

    def test_partial_match_scores_medium(self):
        from unified_api.services.comp_builder import score_deal_similarity
        criteria = {"indication": "NSCLC", "phase": "Phase 2", "modality": "ADC"}
        deal = {"indication": "Breast Cancer", "phase": "Phase 2", "modality": "ADC"}
        score = score_deal_similarity(criteria, deal)
        assert 0.3 <= score <= 0.8

    def test_score_is_between_0_and_1(self):
        from unified_api.services.comp_builder import score_deal_similarity
        criteria = {"indication": "test"}
        deal = {"indication": "test"}
        score = score_deal_similarity(criteria, deal)
        assert 0.0 <= score <= 1.0

    def test_empty_criteria_returns_zero(self):
        from unified_api.services.comp_builder import score_deal_similarity
        score = score_deal_similarity({}, {"indication": "test"})
        assert score == 0.0


class TestCompSetStats:
    """Test statistical summary of comp set."""

    def test_compute_stats_with_values(self):
        from unified_api.services.comp_builder import compute_comp_stats
        deals = [
            {"total_value": 100},
            {"total_value": 200},
            {"total_value": 300},
            {"total_value": 400},
            {"total_value": 500},
        ]
        stats = compute_comp_stats(deals)
        assert stats["count"] == 5
        assert stats["disclosed"] == 5
        assert stats["mean"] == 300.0
        assert stats["median"] == 300.0
        assert stats["min"] == 100
        assert stats["max"] == 500

    def test_compute_stats_with_nulls(self):
        from unified_api.services.comp_builder import compute_comp_stats
        deals = [
            {"total_value": 100},
            {"total_value": None},
            {"total_value": 300},
        ]
        stats = compute_comp_stats(deals)
        assert stats["count"] == 3
        assert stats["disclosed"] == 2
        assert stats["mean"] == 200.0

    def test_compute_stats_empty(self):
        from unified_api.services.comp_builder import compute_comp_stats
        stats = compute_comp_stats([])
        assert stats["count"] == 0
        assert stats["disclosed"] == 0
        assert stats["mean"] is None
        assert stats["median"] is None
