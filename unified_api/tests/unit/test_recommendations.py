"""
TDD: Recommendation engine tests.
"""
import pytest


class TestRecommendations:

    def test_score_deal_relevance_returns_float(self):
        from unified_api.services.recommendations import score_deal_relevance
        score = score_deal_relevance(
            deal={"indication": "NSCLC", "value": 500},
            user_interests=["oncology", "NSCLC"],
        )
        assert isinstance(score, float)
        assert 0 <= score <= 1

    def test_generate_reasons_returns_list(self):
        from unified_api.services.recommendations import generate_reasons
        reasons = generate_reasons(
            deal={"indication": "NSCLC", "value": 500, "agreement_type": "M&A"},
            matched_on=["indication"],
        )
        assert isinstance(reasons, list)
        assert len(reasons) > 0
        assert all(isinstance(r, str) for r in reasons)
