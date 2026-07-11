"""Tests for source-sync freshness classification."""

from datetime import date, datetime, timedelta, timezone

from unified_api.routers.health import _backfill_progress, _sync_freshness


def test_recent_completed_sync_is_ok():
    result = _sync_freshness(
        datetime.now(timezone.utc) - timedelta(hours=2),
        warn_hours=24,
        critical_hours=48,
        run_status="completed",
    )

    assert result["status"] == "ok"
    assert 1.9 <= result["age_hours"] <= 2.1


def test_stale_sync_is_critical():
    result = _sync_freshness(
        datetime.now(timezone.utc) - timedelta(hours=72),
        warn_hours=24,
        critical_hours=48,
        run_status="completed",
    )

    assert result["status"] == "critical"


def test_failed_sync_is_critical_even_when_recent():
    result = _sync_freshness(
        datetime.now(timezone.utc),
        warn_hours=24,
        critical_hours=48,
        run_status="failed",
    )

    assert result["status"] == "critical"


def test_partial_sync_is_warning_even_when_recent():
    result = _sync_freshness(
        datetime.now(timezone.utc),
        warn_hours=24,
        critical_hours=48,
        run_status="partial",
    )

    assert result["status"] == "warning"


def test_missing_sync_state_is_critical():
    result = _sync_freshness(None, 24, 48)

    assert result == {
        "status": "critical",
        "age_hours": None,
        "detail": "no completed run",
    }


def test_first_running_sync_without_completion_reports_running():
    result = _sync_freshness(None, 24, 48, "running")

    assert result["status"] == "running"
    assert result["age_hours"] is None


def test_backfill_progress_uses_observed_cursor_throughput():
    result = _backfill_progress(
        cursor=date(2026, 1, 15),
        target=date(2026, 2, 12),
        runs=[
            {
                "status": "completed",
                "cursor_start": date(2026, 1, 1),
                "cursor_end": date(2026, 1, 8),
                "started_at": "2026-02-12T00:00:00Z",
                "completed_at": "2026-02-12T01:00:00Z",
                "filings_fetched": 14,
            },
            {
                "status": "completed",
                "cursor_start": date(2026, 1, 8),
                "cursor_end": date(2026, 1, 15),
                "started_at": "2026-02-12T02:00:00Z",
                "completed_at": "2026-02-12T03:00:00Z",
                "filings_fetched": 14,
            },
        ],
        schedule_interval_hours=2,
    )

    assert result["backlog_days"] == 28
    assert result["runs_sampled"] == 2
    assert result["cursor_days_per_run"] == 7
    assert result["filings_per_hour"] == 14
    assert result["estimated_runs_remaining"] == 4
    assert result["estimated_catchup_hours"] == 8
    assert result["estimate_status"] == "observed"


def test_backfill_progress_falls_back_until_history_accumulates():
    result = _backfill_progress(
        cursor=date(2026, 2, 1),
        target=date(2026, 2, 15),
        runs=[],
        schedule_interval_hours=2,
        fallback_days_per_run=7,
    )

    assert result["estimated_runs_remaining"] == 2
    assert result["estimated_catchup_hours"] == 4
    assert result["estimate_status"] == "configured_capacity"


def test_backfill_progress_reports_caught_up():
    result = _backfill_progress(
        cursor=date(2026, 2, 15),
        target=date(2026, 2, 15),
        runs=[],
    )

    assert result["backlog_days"] == 0
    assert result["estimated_runs_remaining"] == 0
    assert result["estimate_status"] == "caught_up"
