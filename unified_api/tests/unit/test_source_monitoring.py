"""Tests for common source-job state classification and alert deduplication."""

from datetime import datetime, timedelta, timezone

from unified_api.services.source_monitoring import (
    SourcePolicy,
    classify_source_job,
    notification_transition,
    retry_delay,
)


NOW = datetime(2026, 7, 11, 18, 0, tzinfo=timezone.utc)
POLICY = SourcePolicy("Test Source", warn_hours=24, critical_hours=48)


def test_completed_source_is_ok_inside_warning_window():
    severity, detail = classify_source_job(
        {"status": "completed", "last_success_at": NOW - timedelta(hours=2)},
        POLICY,
        now=NOW,
    )
    assert severity == "ok"
    assert "2.0h" in detail


def test_stale_source_moves_from_warning_to_critical():
    warning, _ = classify_source_job(
        {"status": "completed", "last_success_at": NOW - timedelta(hours=30)},
        POLICY,
        now=NOW,
    )
    critical, _ = classify_source_job(
        {"status": "completed", "last_success_at": NOW - timedelta(hours=50)},
        POLICY,
        now=NOW,
    )
    assert warning == "warning"
    assert critical == "critical"


def test_failed_run_is_critical_even_after_recent_success():
    severity, detail = classify_source_job(
        {
            "status": "failed",
            "last_success_at": NOW - timedelta(minutes=5),
            "last_error": "source timeout",
        },
        POLICY,
        now=NOW,
    )
    assert severity == "critical"
    assert "source timeout" in detail


def test_first_running_job_does_not_alert_before_it_finishes():
    assert classify_source_job(
        {"status": "running", "last_success_at": None}, POLICY, now=NOW
    )[0] == "ok"


def test_alert_transitions_are_deduplicated_and_recovery_is_emitted():
    assert notification_transition("ok", "warning") == "alert"
    assert notification_transition("warning", "warning") is None
    assert notification_transition("warning", "critical") == "alert"
    assert notification_transition("critical", "ok") == "recovery"
    assert notification_transition("ok", "ok") is None


def test_retry_advisory_uses_capped_exponential_backoff():
    assert retry_delay(1) == timedelta(minutes=15)
    assert retry_delay(3) == timedelta(minutes=60)
    assert retry_delay(20) == timedelta(hours=6)
