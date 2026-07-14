"""Tests for common source-job state classification and alert deduplication."""

from datetime import datetime, timedelta, timezone

from unified_api.services.source_monitoring import (
    _source_counts,
    SourcePolicy,
    classify_source_job,
    notification_transition,
    retry_delay,
    source_job_payload,
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


def test_common_edgar_counts_have_stable_vocabulary():
    counts = _source_counts("edgar_backfill", {
        "filings_seen": 12,
        "filings_fetched": 5,
        "documents_created": 8,
        "chunks_created": 90,
    })

    assert counts == {
        "records_seen": 12,
        "records_processed": 5,
        "records_created": 5,
        "records_updated": None,
        "documents_created": 8,
        "chunks_created": 90,
        "relationships_processed": None,
    }


def test_contract_scan_counts_have_stable_vocabulary():
    counts = _source_counts("cortellis_contracts", {
        "eligible_deals": 149_006,
        "processed": 1000,
        "completed": 998,
        "contracts_observed": 240,
    })

    assert counts == {
        "records_seen": 149_006,
        "records_processed": 1000,
        "records_created": None,
        "records_updated": 998,
        "documents_created": 240,
        "chunks_created": None,
        "relationships_processed": None,
    }


def test_deal_api_scan_counts_have_stable_vocabulary():
    counts = _source_counts("cortellis_deal_api", {
        "eligible_deals": 149_028,
        "processed": 500,
        "completed": 499,
        "sources_observed": 675,
    })

    assert counts == {
        "records_seen": 149_028,
        "records_processed": 500,
        "records_created": None,
        "records_updated": 499,
        "documents_created": 675,
        "chunks_created": None,
        "relationships_processed": None,
    }


def test_common_source_payload_reports_cursor_lag_duration_and_counts():
    payload = source_job_payload({
        "source_key": "edgar_backfill",
        "source_cursor": "2026-07-10",
        "source_data_at": datetime(2026, 7, 10, tzinfo=timezone.utc),
        "duration_seconds": 42.5,
        "counts": {"records_processed": 10},
    }, now=NOW)

    assert payload["payload_version"] == 1
    assert payload["cursor"] == "2026-07-10"
    assert payload["source_lag_seconds"] == 86400 + 18 * 3600
    assert payload["duration_seconds"] == 42.5
    assert payload["counts"] == {"records_processed": 10}
