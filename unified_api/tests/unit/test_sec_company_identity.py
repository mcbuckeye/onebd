"""Tests for source-gated SEC company identity enrichment."""

import pytest

from unified_api.services.sec_company_identity import (
    _normalize_cik,
    sec_identity_name_match,
    sec_submission_identifiers,
    validate_roche_wtw_repair_sources,
)


def test_cik_normalization_is_zero_padded_and_strict():
    assert _normalize_cik("78003") == "0000078003"
    assert _normalize_cik("CIK 0000078003") == "0000078003"
    with pytest.raises(ValueError, match="Invalid SEC CIK"):
        _normalize_cik("")


def test_sec_name_match_accepts_only_normalized_exact_name_or_alias():
    matched, candidate = sec_identity_name_match(
        "PFIZER INC.",
        ["Pfizer Inc", "Pfizer Corporation"],
    )
    assert matched is True
    assert candidate == "Pfizer Inc"

    matched, candidate = sec_identity_name_match(
        "NOVARTIS AG",
        ["Novartis Holdings Ltd"],
    )
    assert matched is True
    assert candidate == "Novartis Holdings Ltd"


def test_sec_name_match_rejects_roche_cik_that_belongs_to_willis():
    matched, candidate = sec_identity_name_match(
        "WILLIS TOWERS WATSON PLC",
        ["Roche Holding Ltd", "ROCHE HOLDING"],
    )
    assert matched is False
    assert candidate is None


def test_roche_wtw_repair_requires_both_exact_official_sec_identities():
    validate_roche_wtw_repair_sources(
        {"cik": "0001140536", "name": "WILLIS TOWERS WATSON PLC"},
        {"cik": "0000889131", "name": "ROCHE HOLDING LTD"},
    )

    with pytest.raises(ValueError, match="expected legal name"):
        validate_roche_wtw_repair_sources(
            {"cik": "0001140536", "name": "Roche Holding Ltd"},
            {"cik": "0000889131", "name": "ROCHE HOLDING LTD"},
        )


def test_missing_company_seed_uses_official_roche_subject_cik():
    from unified_api.scripts.add_missing_edgar_companies import MISSING_COMPANIES

    roche = next(item for item in MISSING_COMPANIES if item["name"] == "Roche Holding Ltd")
    assert roche["cik"] == "0000889131"


def test_sec_identifiers_normalize_lei_and_distinct_domains():
    identifiers = sec_submission_identifiers({
        "lei": "549300U41AUUVOAAOB37",
        "website": "https://www.example.com/investors",
        "investorWebsite": "https://example.com/relations",
    })

    assert identifiers == [
        {
            "identifier_type": "lei",
            "identifier_value": "549300U41AUUVOAAOB37",
            "normalized_value": "549300U41AUUVOAAOB37",
            "source_field": "lei",
        },
        {
            "identifier_type": "domain",
            "identifier_value": "https://www.example.com/investors",
            "normalized_value": "example.com",
            "source_field": "website",
        },
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"lei": "not-an-lei"},
        {"website": "not a domain"},
    ],
)
def test_sec_identifiers_reject_invalid_source_values(payload):
    with pytest.raises(ValueError):
        sec_submission_identifiers(payload)
