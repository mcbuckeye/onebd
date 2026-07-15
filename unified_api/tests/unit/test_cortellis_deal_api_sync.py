"""Unit tests for lossless Cortellis response and source scanning."""

import hashlib
from unittest.mock import Mock, patch

import pytest

from src.api_client import DealRecord, DealSourcesRecord
from unified_api.services.cortellis_deal_api_sync import (
    DEAL_SOURCES_ENDPOINT,
    _attach_catalog_cardinality,
    _archive_source_response,
    _finalize_scan_result,
    _validate_expanded_record,
)


def test_validate_expanded_record_requires_matching_payload_id():
    record = DealRecord(
        id=42,
        raw_xml='<dealRecordOutput id="42"><Title>Test</Title></dealRecordOutput>',
        parsed_data={"@attributes": {"id": "42"}, "Title": "Test"},
    )

    _validate_expanded_record(42, record)


@pytest.mark.parametrize(
    "record",
    [
        DealRecord(
            id=41,
            raw_xml='<dealRecordOutput id="41"/>',
            parsed_data={"@attributes": {"id": "41"}},
        ),
        DealRecord(
            id=42,
            raw_xml='<dealRecordOutput id="41"/>',
            parsed_data={"@attributes": {"id": "41"}},
        ),
        DealRecord(id=42, raw_xml="", parsed_data={"@attributes": {"id": "42"}}),
    ],
)
def test_validate_expanded_record_rejects_untrustworthy_payloads(record):
    with pytest.raises(ValueError):
        _validate_expanded_record(42, record)


def test_archive_source_response_hashes_and_preserves_exact_body():
    raw_xml = (
        '<dealSourcesOutput><Sources><Source id="123" type="News"/>'
        '</Sources></dealSourcesOutput>'
    )
    record = DealSourcesRecord(deal_id=42, raw_response=raw_xml, sources=[])
    session = Mock()

    digest = _archive_source_response(session, record)

    assert digest == hashlib.sha256(raw_xml.encode("utf-8")).hexdigest()
    params = session.execute.call_args.args[1]
    assert params["deal_id"] == 42
    assert params["endpoint"] == DEAL_SOURCES_ENDPOINT
    assert params["response_sha256"] == digest
    assert params["response_body"] == raw_xml


def test_archive_source_response_rejects_empty_body():
    with pytest.raises(ValueError, match="was empty"):
        _archive_source_response(
            Mock(),
            DealSourcesRecord(deal_id=42, raw_response="", sources=[]),
        )


def test_catalog_cardinality_uses_exhaustive_proof_not_advertised_count():
    search_result = Mock(total_results=149_028)
    with (
        patch(
            "unified_api.services.cortellis_deal_api_sync.CortellisClient"
        ) as client_class,
        patch(
            "unified_api.services.cortellis_deal_api_sync._latest_catalog_proof",
            return_value={
                "retrievable_total": 172_638,
                "last_success_at": None,
            },
        ),
    ):
        client_class.return_value.__enter__.return_value.search_deals.return_value = (
            search_result
        )
        complete = _attach_catalog_cardinality({
            "coverage_complete": True,
            "eligible_deals": 172_638,
        })
        incomplete = _attach_catalog_cardinality({
            "coverage_complete": True,
            "eligible_deals": 172_637,
        })

    assert complete["catalog_total"] == 149_028
    assert complete["verified_retrievable_total"] == 172_638
    assert complete["catalog_membership_complete"] is True
    assert incomplete["catalog_membership_complete"] is False


def test_complete_lossless_scan_promotes_verified_catalog_total():
    session = Mock()
    session_context = Mock()
    session_context.__enter__ = Mock(return_value=session)
    session_context.__exit__ = Mock(return_value=False)
    result = {
        "coverage_complete": True,
        "eligible_deals": 172_675,
    }
    with (
        patch(
            "unified_api.services.cortellis_deal_api_sync.get_cortellis_session",
            return_value=session_context,
        ),
        patch(
            "unified_api.services.cortellis_deal_api_sync."
            "advance_catalog_proof_to_verified_total"
        ) as advance,
        patch(
            "unified_api.services.cortellis_deal_api_sync."
            "_attach_catalog_cardinality",
            side_effect=lambda value: value,
        ),
    ):
        finalized = _finalize_scan_result(result)

    advance.assert_called_once_with(
        session,
        verified_retrievable_total=172_675,
    )
    assert finalized is result


def test_incomplete_scan_cannot_promote_catalog_total():
    result = {
        "coverage_complete": False,
        "eligible_deals": 172_675,
    }
    with (
        patch(
            "unified_api.services.cortellis_deal_api_sync."
            "advance_catalog_proof_to_verified_total"
        ) as advance,
        patch(
            "unified_api.services.cortellis_deal_api_sync."
            "_attach_catalog_cardinality",
            side_effect=lambda value: value,
        ),
    ):
        _finalize_scan_result(result)

    advance.assert_not_called()
