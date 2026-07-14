"""Exact deal-to-trial citation and timeline tests."""

from datetime import date
from unittest.mock import MagicMock, patch


def test_nct_parser_normalizes_exact_ids_and_retains_offsets():
    from unified_api.services.deal_evidence_timeline import extract_nct_citations

    source = "<para>Registered as nct01234567; confirm NCT87654321.</para>"
    citations = extract_nct_citations(source)

    assert [item["nct_id"] for item in citations] == [
        "NCT01234567",
        "NCT87654321",
    ]
    for item in citations:
        raw = source[item["source_char_start"]:item["source_char_end"]]
        assert raw.upper() == item["nct_id"]
        assert "<para>" not in item["source_excerpt"]


def test_nct_parser_rejects_partial_or_embedded_identifiers():
    from unified_api.services.deal_evidence_timeline import extract_nct_citations

    source = (
        "NCT1234567 NCT123456789 XNCT12345678 NCT12345678A "
        "and the unrelated number 12345678"
    )

    assert extract_nct_citations(source) == []


def test_nct_parser_does_not_deduplicate_distinct_source_mentions():
    from unified_api.services.deal_evidence_timeline import extract_nct_citations

    citations = extract_nct_citations("NCT01234567 and later NCT01234567")

    assert len(citations) == 2
    assert citations[0]["source_char_start"] != citations[1]["source_char_start"]


def test_timeline_combines_explicit_milestones_and_exact_trial_dates():
    from unified_api.services.deal_evidence_timeline import (
        build_deal_evidence_timeline,
    )

    evidence = [{
        "source_record_id": 99,
        "source_sha256": "a" * 64,
        "source_excerpt": "Study NCT01234567",
    }]
    events = build_deal_evidence_timeline(
        [{
            "id": 7,
            "event_date": date(2024, 1, 2),
            "event_type": "Regulatory Milestone",
            "stage": "Registered",
            "summary": "<para>NDA accepted.</para>",
        }],
        [{
            "nct_id": "NCT01234567",
            "brief_title": "Pivotal study",
            "overall_status": "RECRUITING",
            "phases": ["PHASE3"],
            "start_date": date(2023, 6, 1),
            "start_date_raw": "2023-06-01",
            "start_date_type": "ACTUAL",
            "primary_completion_date": date(2025, 8, 1),
            "primary_completion_date_raw": "2025-08",
            "primary_completion_date_type": "ESTIMATED",
            "completion_date": None,
            "last_update_posted": date(2025, 2, 3),
            "last_update_posted_raw": "2025-02-03",
            "source_url": "https://clinicaltrials.gov/study/NCT01234567",
            "citation_evidence": evidence,
        }],
    )

    regulatory = next(event for event in events if event["category"] == "regulatory")
    primary = next(event for event in events if event["event_type"] == "Primary completion")
    status = next(event for event in events if event["category"] == "clinical_status")
    assert regulatory["summary"] == "NDA accepted."
    assert primary["date_precision"] == "2025-08"
    assert primary["date_type"] == "ESTIMATED"
    assert primary["link_method"] == "exact_nct_citation"
    assert primary["citation_evidence"] == evidence
    assert "current status: RECRUITING" in status["summary"]
    assert events[0]["event_date"] == "2025-08-01"


def test_timeline_preserves_citation_when_registry_record_is_unavailable():
    from unified_api.services.deal_evidence_timeline import (
        build_deal_evidence_timeline,
    )

    events = build_deal_evidence_timeline([], [{
        "nct_id": "NCT99999999",
        "brief_title": None,
        "source_url": None,
        "citation_evidence": [{"source_excerpt": "NCT99999999"}],
    }])

    assert events == [{
        "source": "clinicaltrials.gov_api_v2",
        "source_record_id": "NCT99999999",
        "source_url": None,
        "nct_id": "NCT99999999",
        "link_method": "exact_nct_citation",
        "citation_evidence": [{"source_excerpt": "NCT99999999"}],
        "event_date": None,
        "date_precision": None,
        "category": "clinical_trial",
        "event_type": "Cited trial unavailable in registry",
        "stage": None,
        "summary": "NCT99999999 is cited in the Cortellis deal payload.",
    }]


def test_deal_trial_link_batch_returns_busy_when_lock_is_held():
    from unified_api.services.deal_evidence_timeline import (
        DEAL_TRIAL_LINK_PARSER_VERSION,
        extract_deal_trial_link_batch,
    )

    session = MagicMock()
    session.execute.return_value.scalar.return_value = False

    assert extract_deal_trial_link_batch(session) == {
        "status": "busy",
        "processed": 0,
        "citation_mentions": 0,
        "cited_trials": 0,
        "errors": 0,
        "parser_version": DEAL_TRIAL_LINK_PARSER_VERSION,
    }


def test_link_validation_requires_full_replayable_population(monkeypatch):
    from unified_api.services import deal_evidence_timeline

    monkeypatch.setattr(
        deal_evidence_timeline,
        "deal_trial_link_status",
        lambda _session: {
            "scan_coverage_pct": 100.0,
            "failed_deals": 0,
            "citation_mentions": 10,
            "cited_nct_ids": 8,
            "registry_matched_nct_ids": 8,
        },
    )
    session = MagicMock()
    session.execute.return_value.mappings.return_value.one.return_value = {
        "invalid_nct_ids": 0,
        "invalid_provenance": 0,
        "missing_source_records": 0,
        "source_hash_mismatches": 0,
        "source_offset_mismatches": 0,
    }

    report = deal_evidence_timeline.deal_trial_link_validation_status(session)

    assert report["registry_match_pct"] == 100.0
    assert report["technical_release_ready"] is True


def test_link_validation_stays_blocked_until_scan_is_complete(monkeypatch):
    from unified_api.services import deal_evidence_timeline

    monkeypatch.setattr(
        deal_evidence_timeline,
        "deal_trial_link_status",
        lambda _session: {
            "scan_coverage_pct": 99.99,
            "failed_deals": 0,
            "citation_mentions": 10,
            "cited_nct_ids": 8,
            "registry_matched_nct_ids": 8,
        },
    )
    session = MagicMock()
    session.execute.return_value.mappings.return_value.one.return_value = {
        "invalid_nct_ids": 0,
        "invalid_provenance": 0,
        "missing_source_records": 0,
        "source_hash_mismatches": 0,
        "source_offset_mismatches": 0,
    }

    report = deal_evidence_timeline.deal_trial_link_validation_status(session)

    assert report["technical_release_ready"] is False


def test_celery_deal_trial_link_task_runs_bounded_batch():
    expected = {
        "status": "completed",
        "processed": 5000,
        "citation_mentions": 12,
        "cited_trials": 10,
        "errors": 0,
        "parser_version": 1,
    }
    session = MagicMock()
    context = MagicMock()
    context.__enter__.return_value = session
    with (
        patch(
            "unified_api.services.database.get_cortellis_session",
            return_value=context,
        ),
        patch(
            "unified_api.services.deal_evidence_timeline."
            "extract_deal_trial_link_batch",
            return_value=expected,
        ) as extract,
    ):
        from unified_api.workers.celery_app import (
            extract_deal_clinical_trial_links,
        )

        assert extract_deal_clinical_trial_links.run() == expected

    extract.assert_called_once_with(session, batch_size=5000)
