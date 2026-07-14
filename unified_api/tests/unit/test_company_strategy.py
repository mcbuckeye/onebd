"""Grounded company-strategy intelligence tests."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from unified_api.services.company_strategy import (
    _competitive_peers,
    _jaccard,
    _momentum_label,
    company_indication_entrant_snapshot,
    company_strategy_intelligence,
)


def _result(*, one_or_none=None, one=None, all_rows=None):
    mappings = SimpleNamespace(
        one_or_none=lambda: one_or_none,
        one=lambda: one,
        all=lambda: all_rows or [],
    )
    return SimpleNamespace(mappings=lambda: mappings)


def test_jaccard_and_momentum_are_deterministic():
    assert _jaccard(set(), set()) == 0.0
    assert _jaccard({1, 2}, {2, 3}) == 1 / 3
    assert _momentum_label(8, 0) == ("newly active", None)
    assert _momentum_label(0, 0) == ("no recent activity", None)
    assert _momentum_label(15, 10) == ("accelerating", 50.0)
    assert _momentum_label(7, 10) == ("slowing", -30.0)
    assert _momentum_label(11, 10) == ("steady", 10.0)


def test_competitive_map_scores_only_observed_normalized_overlap():
    session = MagicMock()
    session.execute.return_value = _result(all_rows=[{
        "id": 22,
        "name": "Example Peer",
        "company_type": "Biotechnology",
        "shared_entities": 2,
        "overlap_deal_ids": [901, 900],
        "indication_ids": [1, 2],
        "technology_ids": [10],
        "asset_ids": [999],
        "direct_partner_deals": 3,
    }])
    focus = {
        "indications": [{"id": 1, "name": "Cancer"}],
        "technologies": [{"id": 10, "name": "Antibody"}],
        "assets": [{"id": 100, "name": "Asset A"}],
        "agreement_types": [],
        "partners": [],
    }

    peers = _competitive_peers(
        session,
        company_id=11,
        years=5,
        focus=focus,
        limit=10,
    )

    assert peers == [{
        "company_id": 22,
        "company_name": "Example Peer",
        "company_type": "Biotechnology",
        "overlap_score": 50.0,
        "dimension_scores": {
            "indications": 50.0,
            "technologies": 100.0,
            "assets": 0.0,
        },
        "shared_indications": [{"id": 1, "name": "Cancer"}],
        "shared_technologies": [{"id": 10, "name": "Antibody"}],
        "shared_assets": [],
        "direct_partner_deals": 3,
        "evidence_deal_ids": [901, 900],
    }]
    params = session.execute.call_args.args[1]
    assert params["company_id"] == 11
    assert params["indication_ids"] == [1]
    assert params["technology_ids"] == [10]
    assert params["drug_ids"] == [100]


def test_strategy_summary_is_evidence_limited_and_clamps_windows():
    session = MagicMock()
    session.execute.side_effect = [
        _result(one_or_none={
            "id": 19446,
            "name": "Roche Holding Ltd",
            "company_type": "Pharmaceutical",
            "hq_location": "Switzerland",
            "ticker": None,
        }),
        _result(one={
            "deal_count": 12,
            "principal_deals": 7,
            "partner_deals": 5,
            "recent_12_month_deals": 6,
            "prior_12_month_deals": 3,
            "disclosed_value_deals": 4,
            "average_deal_value": 125.0,
            "window_first_deal_date": date(2024, 1, 1),
            "window_last_deal_date": date(2026, 6, 1),
        }),
    ]
    focus = {
        "indications": [{
            "id": 1,
            "name": "Cancer",
            "deal_count": 9,
            "evidence_deal_ids": [12, 11],
        }],
        "technologies": [],
        "agreement_types": [{
            "name": "Licensing",
            "deal_count": 8,
            "evidence_deal_ids": [12],
        }],
        "assets": [],
        "partners": [{
            "id": 2,
            "name": "Example Partner",
            "deal_count": 3,
            "evidence_deal_ids": [12, 10],
        }],
    }

    with (
        patch(
            "unified_api.services.company_strategy._focus_rows",
            return_value=focus,
        ) as focus_rows,
        patch(
            "unified_api.services.company_strategy._competitive_peers",
            return_value=[{"company_id": 2}],
        ),
        patch(
            "unified_api.services.company_strategy._new_indication_entrants",
            return_value=[{"company_id": 3}],
        ),
    ):
        result = company_strategy_intelligence(
            session,
            19446,
            years=100,
            peer_limit=100,
            entrant_days=1,
        )

    assert result is not None
    assert result["window"]["years"] == 20
    assert result["activity"]["momentum"] == "accelerating"
    assert result["activity"]["momentum_change_pct"] == 100.0
    assert result["strategy_statements"][1]["evidence_deal_ids"] == [12, 11]
    assert "do not infer management intent" in result["methodology"]["strategy_scope"]
    assert result["competitive_map"] == [{"company_id": 2}]
    assert result["new_indication_entrants"] == [{"company_id": 3}]
    focus_rows.assert_called_once_with(session, 19446, 20)


def test_strategy_returns_none_for_unknown_company():
    session = MagicMock()
    session.execute.return_value = _result(one_or_none=None)

    assert company_strategy_intelligence(session, 999999) is None
    assert session.execute.call_count == 1


def test_entrant_snapshot_uses_the_same_bounded_company_focus(monkeypatch):
    focus = {
        "indications": [
            {"id": index, "name": f"Indication {index}"}
            for index in range(1, 6)
        ],
        "technologies": [],
        "agreement_types": [],
        "assets": [],
        "partners": [],
    }
    focus_rows = MagicMock(return_value=focus)
    entrant_rows = MagicMock(return_value=[{"company_id": 22}])
    monkeypatch.setattr(
        "unified_api.services.company_strategy._focus_rows",
        focus_rows,
    )
    monkeypatch.setattr(
        "unified_api.services.company_strategy._new_indication_entrants",
        entrant_rows,
    )

    result = company_indication_entrant_snapshot(
        MagicMock(),
        11,
        years=100,
        entrant_days=1,
        limit=1000,
    )

    assert result["top_indications"] == focus["indications"][:3]
    assert result["entrants"] == [{"company_id": 22}]
    assert focus_rows.call_args.args[2] == 20
    assert entrant_rows.call_args.kwargs["entrant_days"] == 30
    assert entrant_rows.call_args.kwargs["limit"] == 500
