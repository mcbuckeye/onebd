"""
TDD: Comp builder tests — write these FIRST, then implement.
"""

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

    def test_common_abbreviation_matches_full_indication_name(self):
        from unified_api.services.comp_builder import score_deal_similarity

        score = score_deal_similarity(
            {"indication": "NSCLC"},
            {"indication": "Non-small-cell lung cancer"},
        )

        assert score == 1.0


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


class TestCompCandidateFilters:
    """Requested dimensions must constrain the SQL candidate pool."""

    def test_modality_is_applied_before_similarity_ranking(self):
        from unified_api.routers.comps import (
            CompBuildRequest,
            build_comp_dimension_selects,
            build_comp_filters,
        )

        request = CompBuildRequest(
            indication="NSCLC",
            phase="Phase 2",
            modality="bispecific",
            deal_type="License",
        )
        conditions, params = build_comp_filters(request)
        indication_select, modality_select = build_comp_dimension_selects(request)

        where = " ".join(conditions)
        assert "deal_technologies" in where
        assert "deal_technologies" in where
        assert "public_drug_profiles" in where
        assert "drug_chembl_records" in where
        assert params["modality_patterns"] == ["%bispecific%"]
        assert "NOT ILIKE ALL" in where
        assert "indication_patterns" in indication_select
        assert "modality_patterns" in modality_select

    def test_adc_shorthand_expands_to_full_modality_names(self):
        from unified_api.routers.comps import CompBuildRequest, build_comp_filters

        _, params = build_comp_filters(CompBuildRequest(modality="ADC"))

        assert "%adc%" in params["modality_patterns"]
        assert "%antibody-drug conjugate%" in params["modality_patterns"]

    def test_nsclc_expands_to_source_taxonomy_spellings(self):
        from unified_api.routers.comps import CompBuildRequest, build_comp_filters

        _, params = build_comp_filters(CompBuildRequest(indication="NSCLC"))

        assert "%nsclc%" in params["indication_patterns"]
        assert "%non%small%cell%lung%cancer%" in params["indication_patterns"]

    def test_terminated_deals_can_be_included_explicitly(self):
        from unified_api.routers.comps import CompBuildRequest, build_comp_filters

        conditions, _ = build_comp_filters(
            CompBuildRequest(indication="Oncology", include_terminated=True)
        )

        assert "NOT ILIKE ALL" not in " ".join(conditions)

    def test_empty_request_is_rejected(self):
        import pytest
        from pydantic import ValidationError
        from unified_api.routers.comps import CompBuildRequest

        with pytest.raises(ValidationError, match="At least one comparison criterion"):
            CompBuildRequest()
