"""Durable first-observed company entrant alert tests."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from unified_api.services.company_entrant_alerts import (
    entrant_alert_content,
    scan_company_entrant_alerts,
)


class _Result:
    def __init__(
        self,
        *,
        scalar=None,
        rows=None,
        scalar_one=None,
        scalar_one_or_none=None,
    ):
        self._scalar = scalar
        self._rows = rows or []
        self._scalar_one = scalar_one
        self._scalar_one_or_none = scalar_one_or_none

    def scalar(self):
        return self._scalar

    def scalar_one(self):
        return self._scalar_one

    def scalar_one_or_none(self):
        return self._scalar_one_or_none

    def mappings(self):
        return SimpleNamespace(all=lambda: self._rows)


def _snapshot():
    return {
        "top_indications": [{"id": 7, "name": "Solid tumor"}],
        "entrants": [{
            "company_id": 22,
            "company_name": "NewCo",
            "company_type": "Biotechnology",
            "indication_id": 7,
            "indication_name": "Solid tumor",
            "first_observed_date": "2026-07-10",
            "observed_deals": 2,
            "evidence_deal_ids": [901, 900],
        }],
    }


def test_alert_language_preserves_the_first_observed_boundary():
    content = entrant_alert_content(
        subject_name="TrackedCo",
        entrant_name="NewCo",
        indication_name="Solid tumor",
        first_observed_date="2026-07-10",
        observed_deals=2,
    )

    assert "first observed" in content
    assert "2 linked deals" in content
    assert "not proof of first-ever market activity" in content


def test_first_scan_establishes_baseline_without_historical_alert_flood():
    session = MagicMock()
    session.execute.side_effect = [
        _Result(scalar=True),
        _Result(rows=[{
            "id": 3,
            "user_id": 5,
            "company_id": 11,
            "company_name": "TrackedCo",
            "entrant_baselined_at": None,
        }]),
        _Result(rows=[]),
        _Result(scalar_one=42),
        _Result(),
    ]
    with (
        patch(
            "unified_api.services.company_entrant_alerts."
            "ensure_company_entrant_alert_schema",
        ),
        patch(
            "unified_api.services.company_entrant_alerts."
            "company_indication_entrant_snapshot",
            return_value=_snapshot(),
        ),
    ):
        result = scan_company_entrant_alerts(session)

    assert result["status"] == "completed"
    assert result["detections_inserted"] == 1
    assert result["trackers_baselined"] == 1
    assert result["alerts_created"] == 0
    assert session.execute.call_count == 5


def test_post_baseline_new_detection_creates_one_deduplicated_alert():
    session = MagicMock()
    session.execute.side_effect = [
        _Result(scalar=True),
        _Result(rows=[{
            "id": 3,
            "user_id": 5,
            "company_id": 11,
            "company_name": "TrackedCo",
            "entrant_baselined_at": datetime.now(timezone.utc),
        }]),
        _Result(rows=[]),
        _Result(scalar_one=42),
        _Result(scalar_one_or_none=99),
        _Result(),
    ]
    with (
        patch(
            "unified_api.services.company_entrant_alerts."
            "ensure_company_entrant_alert_schema",
        ),
        patch(
            "unified_api.services.company_entrant_alerts."
            "company_indication_entrant_snapshot",
            return_value=_snapshot(),
        ),
    ):
        result = scan_company_entrant_alerts(session)

    assert result["alerts_created"] == 1
    alert_params = session.execute.call_args_list[4].args[1]
    assert alert_params["user_id"] == 5
    assert alert_params["detection_id"] == 42
    assert "NewCo" in alert_params["content"]


def test_existing_detection_does_not_emit_duplicate_alert():
    session = MagicMock()
    session.execute.side_effect = [
        _Result(scalar=True),
        _Result(rows=[{
            "id": 3,
            "user_id": 5,
            "company_id": 11,
            "company_name": "TrackedCo",
            "entrant_baselined_at": datetime.now(timezone.utc),
        }]),
        _Result(rows=[{"entrant_company_id": 22, "indication_id": 7}]),
        _Result(scalar_one=42),
        _Result(),
    ]
    with (
        patch(
            "unified_api.services.company_entrant_alerts."
            "ensure_company_entrant_alert_schema",
        ),
        patch(
            "unified_api.services.company_entrant_alerts."
            "company_indication_entrant_snapshot",
            return_value=_snapshot(),
        ),
    ):
        result = scan_company_entrant_alerts(session)

    assert result["detections_inserted"] == 0
    assert result["alerts_created"] == 0
    assert session.execute.call_count == 5


def test_overlapping_scan_returns_busy_without_work():
    session = MagicMock()
    session.execute.return_value = _Result(scalar=False)
    with patch(
        "unified_api.services.company_entrant_alerts."
        "ensure_company_entrant_alert_schema",
    ):
        result = scan_company_entrant_alerts(session)

    assert result == {
        "status": "busy",
        "tracked_companies": 0,
        "detections_inserted": 0,
        "alerts_created": 0,
        "trackers_baselined": 0,
    }


def test_scheduled_task_runs_the_same_durable_scan():
    expected = {
        "status": "completed",
        "tracked_companies": 2,
        "alerts_created": 1,
    }
    context = MagicMock()
    session = context.__enter__.return_value
    with (
        patch(
            "unified_api.services.database.get_cortellis_session",
            return_value=context,
        ),
        patch(
            "unified_api.services.company_entrant_alerts."
            "scan_company_entrant_alerts",
            return_value=expected,
        ) as scan,
    ):
        from unified_api.workers.celery_app import (
            check_company_entrant_alerts,
        )

        assert check_company_entrant_alerts() == expected

    scan.assert_called_once_with(session)
