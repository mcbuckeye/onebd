"""
TDD: Finance detail parser tests.
"""
import pytest


class TestFinanceDetailParser:
    """Test parsing of finance_detail_raw into structured data."""

    def test_parse_upfront_payment(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("Upfront payment of $50 million")
        assert result["upfront"] is not None
        assert result["upfront"]["amount"] == 50
        assert result["upfront"]["currency"] == "USD"

    def test_parse_milestone_payments(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail(
            "Up to $200 million in development milestones and $300 million in commercial milestones"
        )
        assert result["milestones"]["development"] is not None
        assert result["milestones"]["commercial"] is not None

    def test_parse_royalty_rate(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("Tiered royalties ranging from 8% to 15% on net sales")
        assert result["royalties"] is not None
        assert result["royalties"]["min_rate"] == 8
        assert result["royalties"]["max_rate"] == 15

    def test_parse_total_value(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("Total deal value of up to $1.2 billion")
        assert result["total_value"] is not None
        assert result["total_value"]["amount"] == 1200  # in millions

    def test_parse_empty_string(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("")
        assert result["upfront"] is None
        assert result["royalties"] is None
        assert result["total_value"] is None

    def test_parse_none_input(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail(None)
        assert isinstance(result, dict)

    def test_parse_complex_detail(self):
        from unified_api.services.finance_parser import parse_finance_detail
        text = """
        $75 million upfront payment. Up to $500 million in development and
        regulatory milestone payments. Up to $750 million in commercial milestones.
        Tiered royalties from 10% to 20% on worldwide net sales.
        Total potential deal value of approximately $1.325 billion.
        """
        result = parse_finance_detail(text)
        assert result["upfront"]["amount"] == 75
        assert result["total_value"]["amount"] == 1325
        assert result["royalties"]["min_rate"] == 10
        assert result["royalties"]["max_rate"] == 20

    def test_parse_million_abbreviation(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("$50M upfront payment")
        assert result["upfront"]["amount"] == 50

    def test_parse_billion_to_millions(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("Total deal value of $2.5 billion")
        assert result["total_value"]["amount"] == 2500  # stored in millions

    def test_parse_euro_amounts(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("€50 million upfront payment")
        assert result["upfront"] is not None
        assert result["upfront"]["amount"] == 50
        assert result["upfront"]["currency"] == "EUR"

    def test_parse_yen_amounts(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("¥5 billion upfront payment")
        assert result["upfront"] is not None
        assert result["upfront"]["amount"] == 5000  # stored in millions
        assert result["upfront"]["currency"] == "JPY"

    def test_parse_up_to_pattern(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("up to $100 million in milestones")
        # Should extract $100M even with "up to"
        assert result["milestones"]["development"] is not None or \
               result["milestones"]["regulatory"] is not None or \
               result["milestones"]["commercial"] is not None

    def test_parse_approximately_pattern(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("approximately $75 million upfront")
        assert result["upfront"] is not None
        assert result["upfront"]["amount"] == 75

    def test_parse_no_financial_terms_disclosed(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("No financial terms disclosed")
        assert result["upfront"] is None
        assert result["total_value"] is None
        assert result.get("undisclosed", False) is True

    def test_parse_combined_development_regulatory_milestones(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("$500M in development and regulatory milestones")
        # Should capture in development milestones
        assert result["milestones"]["development"] is not None
        assert result["milestones"]["development"]["amount"] == 500

    def test_parse_combined_development_commercial_milestones(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("$400 million in development and commercial milestone payments")
        assert result["milestones"]["development"] is not None
        assert result["milestones"]["development"]["amount"] == 400

    def test_parse_pound_sterling(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("£100 million upfront payment")
        assert result["upfront"] is not None
        assert result["upfront"]["amount"] == 100
        assert result["upfront"]["currency"] == "GBP"

    def test_parse_scientific_milestone(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("$250M in clinical and regulatory milestones")
        assert result["milestones"]["development"] is not None
        assert result["milestones"]["development"]["amount"] == 250

    def test_parse_sales_milestones(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("Up to $600 million in sales-based milestones")
        assert result["milestones"]["commercial"] is not None
        assert result["milestones"]["commercial"]["amount"] == 600

    def test_parse_multiple_currencies_prefers_first(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("€50 million upfront, with additional $100 million in milestones")
        assert result["upfront"]["currency"] == "EUR"
        # Development milestones should be captured even with different currency
        assert result["milestones"]["development"] is not None or \
               result["milestones"]["regulatory"] is not None or \
               result["milestones"]["commercial"] is not None
