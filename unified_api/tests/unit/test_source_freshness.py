"""Tests for source-sync freshness classification."""

from datetime import datetime, timedelta, timezone

from unified_api.routers.health import _sync_freshness


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


def test_missing_sync_state_is_critical():
    result = _sync_freshness(None, 24, 48)

    assert result == {
        "status": "critical",
        "age_hours": None,
        "detail": "no completed run",
    }
