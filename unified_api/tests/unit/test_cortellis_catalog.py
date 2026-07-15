"""Tests for durable exceptions discovered by exhaustive catalog audits."""

from unittest.mock import Mock

import pytest

from src.cortellis_catalog import (
    advance_catalog_proof,
    advance_catalog_proof_to_verified_total,
    assess_catalog_cardinality,
    reconcile_catalog_exclusions,
)


def test_incremental_sync_extends_exhaustive_catalog_baseline():
    session = Mock()

    advance_catalog_proof(session, newly_retrieved=37)

    params = session.execute.call_args.args[1]
    assert params == {"newly_retrieved": 37}
    assert "incremental_retrievable_additions + :newly_retrieved" in str(
        session.execute.call_args.args[0]
    )


def test_complete_scan_can_reconcile_a_stale_catalog_baseline():
    session = Mock()
    session.execute.return_value.scalar_one_or_none.return_value = 37

    changed = advance_catalog_proof_to_verified_total(
        session,
        verified_retrievable_total=172_675,
    )

    assert changed is True
    statement, params = session.execute.call_args.args
    assert params == {"verified_retrievable_total": 172_675}
    assert ":verified_retrievable_total - retrievable_total" in str(statement)
    assert "incremental_retrievable_additions" in str(statement)


def test_verified_catalog_total_must_be_positive():
    with pytest.raises(ValueError, match="must be positive"):
        advance_catalog_proof_to_verified_total(
            Mock(),
            verified_retrievable_total=0,
        )


def test_reconcile_catalog_exclusions_reactivates_and_upserts_retired_ids():
    session = Mock()
    existing_result = Mock()
    existing_result.scalars.return_value = [2, 4]
    session.execute.side_effect = [
        Mock(),
        existing_result,
        Mock(),
        Mock(),
        Mock(),
    ]

    result = reconcile_catalog_exclusions(
        session,
        accessible_ids={1, 2, 3},
        local_only_ids={4, 5},
    )

    assert result == {
        "catalog_exclusions": 2,
        "catalog_exclusions_reactivated": 1,
    }
    delete_params = session.execute.call_args_list[2].args[1]
    assert delete_params == {"deal_ids": [2]}
    inserted_ids = {
        call.args[1]["deal_id"] for call in session.execute.call_args_list[3:]
    }
    assert inserted_ids == {4, 5}


def test_catalog_cardinality_prefers_exhaustive_proof_over_advertised_count():
    result = assess_catalog_cardinality(
        advertised_total=149_028,
        local_total=172_643,
        exclusion_total=5,
        verified_retrievable_total=172_638,
    )

    assert result == {
        "catalog_total": 149_028,
        "local_total": 172_643,
        "catalog_exclusions": 5,
        "eligible_local_total": 172_638,
        "verified_retrievable_total": 172_638,
        "catalog_verification_method": "exhaustive_numeric_id",
        "catalog_gap": 0,
        "catalog_cardinality_complete": True,
    }


def test_catalog_cardinality_falls_back_to_advertised_count_without_proof():
    result = assess_catalog_cardinality(
        advertised_total=149_028,
        local_total=149_027,
        exclusion_total=0,
        verified_retrievable_total=None,
    )

    assert result["catalog_verification_method"] == "advertised_search_fallback"
    assert result["catalog_gap"] == 1
    assert result["catalog_cardinality_complete"] is False
