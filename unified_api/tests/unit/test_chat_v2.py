"""
TDD: Chat v2 synthesis tests — write these FIRST, then implement.
"""
import pytest


class TestFollowUpSuggestions:
    """Test contextual follow-up generation."""

    def test_company_query_gets_company_followups(self):
        from unified_api.services.llm import _suggest_follow_ups
        suggestions = _suggest_follow_ups("What deals has Pfizer done?")
        assert len(suggestions) > 0
        assert len(suggestions) <= 3
        assert all(isinstance(s, str) for s in suggestions)

    def test_oncology_query_gets_oncology_followups(self):
        from unified_api.services.llm import _suggest_follow_ups
        suggestions = _suggest_follow_ups("Show me oncology deal trends")
        assert len(suggestions) > 0
        assert len(suggestions) <= 3

    def test_modality_query_gets_modality_followups(self):
        from unified_api.services.llm import _suggest_follow_ups
        suggestions = _suggest_follow_ups("ADC deals in solid tumors")
        assert len(suggestions) > 0

    def test_valuation_query_gets_financial_followups(self):
        from unified_api.services.llm import _suggest_follow_ups
        suggestions = _suggest_follow_ups("What are typical upfront values?")
        assert len(suggestions) > 0

    def test_generic_query_gets_default_followups(self):
        from unified_api.services.llm import _suggest_follow_ups
        suggestions = _suggest_follow_ups("hello world")
        assert len(suggestions) == 3  # always returns 3 defaults

    def test_followups_are_unique(self):
        from unified_api.services.llm import _suggest_follow_ups
        suggestions = _suggest_follow_ups("Pfizer oncology deals")
        assert len(suggestions) == len(set(suggestions))
