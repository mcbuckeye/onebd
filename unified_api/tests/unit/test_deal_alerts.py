"""
TDD: Deal alerts with contract intelligence tests.

When new contracts appear via cortellis-sync, auto-index and extract key terms,
then push a summary notification.
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


class TestNewContractDetection:
    """Detecting new unprocessed contracts."""

    def test_find_new_contracts(self):
        from unified_api.services.deal_alerts import find_new_contracts

        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = [
            MagicMock(contract_id=1, deal_id=100, word_count=25000, title="New Pfizer deal"),
            MagicMock(contract_id=2, deal_id=200, word_count=18000, title="New Roche deal"),
        ]

        results = find_new_contracts(mock_session, since_hours=24)
        assert len(results) == 2

    def test_no_new_contracts(self):
        from unified_api.services.deal_alerts import find_new_contracts

        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = []

        results = find_new_contracts(mock_session, since_hours=24)
        assert len(results) == 0


class TestAlertSummaryGeneration:
    """Generating deal alert summaries."""

    def test_format_alert_summary(self):
        from unified_api.services.deal_alerts import format_alert_summary

        clauses = {
            "upfront_payment": {"amount": 200, "currency": "USD"},
            "royalty_rates": [{"tier": "net sales", "min_rate": 8, "max_rate": 12}],
            "license_scope": {"type": "exclusive", "field": "oncology"},
            "territories": ["worldwide"],
        }

        summary = format_alert_summary(
            deal_title="Pfizer/BioNTech mRNA oncology collaboration",
            deal_id=12345,
            clauses=clauses,
        )

        assert "Pfizer" in summary
        assert "$200M" in summary or "200" in summary
        assert "exclusive" in summary.lower()

    def test_format_alert_summary_with_redacted_values(self):
        from unified_api.services.deal_alerts import format_alert_summary

        clauses = {
            "upfront_payment": None,
            "royalty_rates": None,
        }

        summary = format_alert_summary(
            deal_title="Deal with no financial terms",
            deal_id=99999,
            clauses=clauses,
        )

        assert "Deal with no financial terms" in summary
