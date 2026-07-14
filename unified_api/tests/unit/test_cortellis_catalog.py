"""Tests for durable exceptions discovered by exhaustive catalog audits."""

from unittest.mock import Mock

from src.cortellis_catalog import reconcile_catalog_exclusions


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
