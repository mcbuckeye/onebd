"""Unit tests for lossless Cortellis response and source scanning."""

import hashlib
from unittest.mock import Mock, patch

import pytest

from src.api_client import DealRecord, DealSourcesRecord
from unified_api.services.cortellis_deal_api_sync import (
    DEAL_SOURCES_ENDPOINT,
    _attach_catalog_cardinality,
    _archive_source_response,
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


def test_catalog_cardinality_certifies_only_complete_equal_coverage():
    search_result = Mock(total_results=149_028)
    with patch(
        "unified_api.services.cortellis_deal_api_sync.CortellisClient"
    ) as client_class:
        client_class.return_value.__enter__.return_value.search_deals.return_value = (
            search_result
        )
        complete = _attach_catalog_cardinality({
            "coverage_complete": True,
            "eligible_deals": 149_028,
        })
        incomplete = _attach_catalog_cardinality({
            "coverage_complete": True,
            "eligible_deals": 149_027,
        })

    assert complete["catalog_membership_complete"] is True
    assert incomplete["catalog_membership_complete"] is False
