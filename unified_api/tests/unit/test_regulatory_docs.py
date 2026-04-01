"""
TDD: Regulatory document search tests.
"""
import pytest
from unittest.mock import MagicMock


class TestRegulatoryDocTypes:
    """Supported regulatory document types."""

    def test_doc_types_defined(self):
        from unified_api.services.regulatory_docs import REGULATORY_DOC_TYPES
        assert "fda_briefing" in REGULATORY_DOC_TYPES
        assert "epar" in REGULATORY_DOC_TYPES
        assert "advisory_committee" in REGULATORY_DOC_TYPES

    def test_doc_type_has_description(self):
        from unified_api.services.regulatory_docs import REGULATORY_DOC_TYPES
        for dtype, info in REGULATORY_DOC_TYPES.items():
            assert "description" in info
            assert "typical_pages" in info


class TestRegulatoryDocSearch:
    """Searching regulatory documents."""

    def test_search_by_drug_and_type(self):
        from unified_api.services.regulatory_docs import search_regulatory_docs

        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = [
            MagicMock(id=1, drug_name="zanubrutinib", doc_type="fda_briefing"),
        ]

        results = search_regulatory_docs(
            mock_session, drug_name="zanubrutinib", doc_type="fda_briefing"
        )
        assert len(results) == 1

    def test_search_all_for_drug(self):
        from unified_api.services.regulatory_docs import search_regulatory_docs

        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = [
            MagicMock(id=1, doc_type="fda_briefing"),
            MagicMock(id=2, doc_type="epar"),
        ]

        results = search_regulatory_docs(mock_session, drug_name="zanubrutinib")
        assert len(results) == 2
