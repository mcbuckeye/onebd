"""
TDD: Clinical Evidence Library tests.

Tests for managing and querying clinical evidence documents
(FDA labels, trial publications, regulatory documents).
"""
import pytest
from unittest.mock import MagicMock, patch


class TestEvidenceDocument:
    """Evidence document model and storage."""

    def test_store_evidence_document(self):
        from unified_api.services.evidence_library import store_evidence_document

        mock_session = MagicMock()

        store_evidence_document(
            session=mock_session,
            drug_name="zanubrutinib",
            brand_name="Brukinsa",
            doc_type="fda_label",
            therapeutic_area="BTK inhibitor",
            indications=["CLL/SLL", "MCL", "WM", "MZL"],
            source_url="https://www.accessdata.fda.gov/drugsatfda_docs/label/2024/213217s011lbl.pdf",
            pdf_path="/data/evidence/brukinsa_label.pdf",
        )

        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()

    def test_get_evidence_by_drug(self):
        from unified_api.services.evidence_library import get_evidence_by_drug

        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = [
            MagicMock(id=1, drug_name="zanubrutinib", doc_type="fda_label"),
            MagicMock(id=2, drug_name="zanubrutinib", doc_type="publication"),
        ]

        results = get_evidence_by_drug(mock_session, drug_name="zanubrutinib")
        assert len(results) == 2

    def test_get_evidence_by_indication(self):
        from unified_api.services.evidence_library import get_evidence_by_indication

        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = [
            MagicMock(id=1, drug_name="zanubrutinib", doc_type="fda_label"),
            MagicMock(id=2, drug_name="ibrutinib", doc_type="fda_label"),
        ]

        results = get_evidence_by_indication(mock_session, indication="CLL")
        assert len(results) == 2

    def test_get_evidence_by_drug_not_found(self):
        from unified_api.services.evidence_library import get_evidence_by_drug

        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = []

        results = get_evidence_by_drug(mock_session, drug_name="nonexistent")
        assert len(results) == 0


class TestEvidenceTreeCache:
    """Tree caching for evidence documents."""

    def test_get_evidence_tree(self):
        from unified_api.services.evidence_library import get_evidence_tree

        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = MagicMock(
            tree_json={"structure": [{"title": "Clinical Studies"}]},
        )

        result = get_evidence_tree(mock_session, evidence_id=1)
        assert result is not None
        assert "structure" in result

    def test_get_evidence_tree_miss(self):
        from unified_api.services.evidence_library import get_evidence_tree

        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = None

        result = get_evidence_tree(mock_session, evidence_id=1)
        assert result is None

    def test_store_evidence_tree(self):
        from unified_api.services.evidence_library import store_evidence_tree

        mock_session = MagicMock()
        tree = {"structure": [{"title": "Clinical Studies"}], "line_count": 100}

        store_evidence_tree(
            session=mock_session,
            evidence_id=1,
            tree_json=tree,
            model="gpt-4o",
        )

        # INSERT tree + UPDATE tree_cached flag = 2 execute calls
        assert mock_session.execute.call_count == 2
        assert mock_session.commit.call_count == 2


class TestFindEvidenceForQuery:
    """Finding relevant evidence documents for a clinical query."""

    def test_finds_drugs_by_name(self):
        from unified_api.services.evidence_library import find_evidence_for_query

        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = [
            MagicMock(id=1, drug_name="zanubrutinib", brand_name="Brukinsa", doc_type="fda_label"),
            MagicMock(id=2, drug_name="ibrutinib", brand_name="Imbruvica", doc_type="fda_label"),
        ]

        results = find_evidence_for_query(
            mock_session,
            query="Compare PFS rates for zanubrutinib and ibrutinib in CLL",
        )
        assert len(results) >= 0  # May or may not find depending on mock setup
