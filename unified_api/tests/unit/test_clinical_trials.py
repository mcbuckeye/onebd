"""Unit tests for the lossless ClinicalTrials.gov API v2 adapter."""

from contextlib import contextmanager
from datetime import date, datetime, timezone
from io import BytesIO
import json
from urllib.parse import parse_qs, urlparse
from urllib.error import HTTPError

import pytest

from unified_api.services import clinical_trials


def _study() -> dict:
    return {
        "protocolSection": {
            "identificationModule": {
                "nctId": "NCT12345678",
                "briefTitle": "A study",
                "officialTitle": "A Lossless Study Record",
            },
            "statusModule": {
                "overallStatus": "RECRUITING",
                "startDateStruct": {"date": "2026-03", "type": "ACTUAL"},
                "primaryCompletionDateStruct": {
                    "date": "2027",
                    "type": "ESTIMATED",
                },
                "lastUpdatePostDateStruct": {"date": "2026-07-13"},
            },
            "designModule": {
                "studyType": "INTERVENTIONAL",
                "phases": ["PHASE2"],
                "enrollmentInfo": {"count": 48, "type": "ESTIMATED"},
            },
            "sponsorCollaboratorsModule": {
                "leadSponsor": {"name": "Example Bio, Inc.", "class": "INDUSTRY"},
                "collaborators": [{"name": "Example University", "class": "OTHER"}],
            },
            "conditionsModule": {
                "conditions": ["Non-Small Cell Lung Cancer"],
                "keywords": ["NSCLC"],
            },
            "armsInterventionsModule": {
                "interventions": [{
                    "type": "DRUG",
                    "name": "ABC-123",
                    "otherNames": ["Examplemab"],
                }],
            },
            "outcomesModule": {
                "primaryOutcomes": [{"measure": "Response rate"}],
                "secondaryOutcomes": [{"measure": "Overall survival"}],
            },
            "contactsLocationsModule": {
                "locations": [{"facility": "Example Cancer Center", "country": "US"}],
            },
        },
        "resultsSection": {"participantFlowModule": {"groups": []}},
        "derivedSection": {"miscInfoModule": {"versionHolder": "2026-07"}},
    }


def test_client_builds_documented_update_query_and_resumes_page(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        return BytesIO(json.dumps({
            "studies": [_study()],
            "nextPageToken": "next-token",
            "totalCount": 17,
        }).encode())

    monkeypatch.setattr(clinical_trials, "urlopen", fake_urlopen)
    client = clinical_trials.ClinicalTrialsClient(
        base_url="https://example.test/api/v2",
        timeout=12,
        delay_seconds=0,
    )
    page = client.updated_studies(
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 13),
        page_size=5000,
        page_token="resume-me",
    )

    query = parse_qs(urlparse(captured["url"]).query)
    assert query["query.term"] == [
        "AREA[LastUpdatePostDate]RANGE[2026-07-01, 2026-07-13]"
    ]
    assert query["sort"] == ["LastUpdatePostDate:asc"]
    assert query["pageSize"] == ["1000"]
    assert query["pageToken"] == ["resume-me"]
    assert captured["timeout"] == 12
    assert page.next_page_token == "next-token"
    assert page.total_count == 17
    assert page.studies[0]["protocolSection"]


def test_dataset_timestamp_treats_source_timestamp_as_new_york_time():
    assert clinical_trials._dataset_timestamp(
        "2026-07-13T09:00:05"
    ) == datetime(2026, 7, 13, 13, 0, 5, tzinfo=timezone.utc)
    assert clinical_trials._dataset_timestamp(
        "2026-01-13T09:00:05"
    ) == datetime(2026, 1, 13, 14, 0, 5, tzinfo=timezone.utc)


def test_recent_window_discards_token_from_an_older_dataset_snapshot():
    session = type("Session", (), {})()
    result = type("Result", (), {})()
    mappings = type("Mappings", (), {})()
    mappings.first = lambda: {
        "lane": "recent",
        "status": "partial",
        "window_start": date(2026, 7, 7),
        "window_end": date(2026, 7, 14),
        "next_page_token": "stale-token",
        "dataset_timestamp": datetime(2026, 7, 14, 13, tzinfo=timezone.utc),
    }
    result.mappings = lambda: mappings
    session.execute = lambda *_args, **_kwargs: result

    state = clinical_trials._initial_window(
        session,
        lane="recent",
        dataset_date=date(2026, 7, 15),
        dataset_timestamp=datetime(2026, 7, 15, 13, tzinfo=timezone.utc),
    )

    assert state["next_page_token"] is None
    assert state["window_end"] == date(2026, 7, 15)


def test_page_fetch_restarts_once_without_a_rejected_token():
    calls = []

    class Client:
        def updated_studies(self, **kwargs):
            calls.append(kwargs["page_token"])
            if kwargs["page_token"]:
                raise HTTPError("https://example.test", 400, "bad token", {}, None)
            return clinical_trials.ClinicalTrialsPage([], None, 0)

    page, reset = clinical_trials._updated_studies_page_with_token_recovery(
        Client(),
        start_date=date(2026, 7, 7),
        end_date=date(2026, 7, 15),
        page_size=1000,
        page_token="stale-token",
    )

    assert reset is True
    assert page.studies == []
    assert calls == ["stale-token", None]


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("2026", date(2026, 1, 1)),
        ("2026-03", date(2026, 3, 1)),
        ("2026-03-09", date(2026, 3, 9)),
    ],
)
def test_partial_dates_preserve_source_precision(raw, normalized):
    assert clinical_trials._normalized_date(raw) == (normalized, raw)


def test_study_parser_preserves_normalized_fields_and_rich_source_arrays():
    fields = clinical_trials._study_fields(_study())

    assert fields["nct_id"] == "NCT12345678"
    assert fields["overall_status"] == "RECRUITING"
    assert fields["phases"] == ["PHASE2"]
    assert fields["enrollment"] == 48
    assert fields["start_date"] == date(2026, 3, 1)
    assert fields["start_date_raw"] == "2026-03"
    assert fields["primary_completion_date"] == date(2027, 1, 1)
    assert fields["primary_completion_date_raw"] == "2027"
    assert fields["lead_sponsor_name"] == "Example Bio, Inc."
    assert fields["conditions"] == ["Non-Small Cell Lung Cancer"]
    assert fields["interventions"][0]["otherNames"] == ["Examplemab"]
    assert fields["primary_outcomes"][0]["measure"] == "Response rate"
    assert fields["locations"][0]["facility"] == "Example Cancer Center"
    assert fields["has_results"] is True


def test_invalid_nct_id_is_rejected():
    study = _study()
    study["protocolSection"]["identificationModule"]["nctId"] = "bad"
    with pytest.raises(ValueError, match="valid NCT ID"):
        clinical_trials._study_fields(study)


def test_drug_alias_match_requires_one_distinct_drug():
    assert clinical_trials._unique_drug_alias_match([
        {"drug_id": 42, "alias_value": "ABC-123", "confidence": 0.95},
        {"drug_id": 42, "alias_value": "abc-123", "confidence": 1.0},
    ]) == {"drug_id": 42, "alias_value": "abc-123", "confidence": 1.0}

    assert clinical_trials._unique_drug_alias_match([
        {"drug_id": 42, "alias_value": "ABC-123", "confidence": 1.0},
        {"drug_id": 84, "alias_value": "ABC-123", "confidence": 1.0},
    ]) is None


def test_reconcile_trial_links_deletes_nonunique_and_promotes_retained(monkeypatch):
    class Result:
        def __init__(self, scalar=None, rowcount=0):
            self._scalar = scalar
            self.rowcount = rowcount

        def scalar(self):
            return self._scalar

    class Session:
        def __init__(self):
            self.results = [
                Result(scalar=131637),
                Result(rowcount=14830),
                Result(rowcount=116807),
                Result(scalar=116807),
            ]

        def execute(self, _statement, _params=None):
            return self.results.pop(0)

    class Connection:
        closed = False

        def execute(self, _statement):
            return Result(scalar=True)

        def close(self):
            self.closed = True

    connection = Connection()

    @contextmanager
    def fake_session():
        yield Session()

    monkeypatch.setattr(clinical_trials, "ensure_clinical_trials_schema", lambda: None)
    monkeypatch.setattr(clinical_trials, "get_cortellis_session", fake_session)
    monkeypatch.setattr(
        clinical_trials,
        "get_cortellis_engine",
        lambda: type("Engine", (), {"connect": lambda _self: connection})(),
    )

    assert clinical_trials.reconcile_clinical_trial_drug_links() == {
        "status": "completed",
        "before": 131637,
        "deleted_unverifiable_or_ambiguous": 14830,
        "promoted_unique_exact": 116807,
        "retained": 116807,
    }
    assert connection.closed is True


def test_global_lock_skips_overlapping_lane(monkeypatch):
    class Result:
        @staticmethod
        def scalar():
            return False

    class Connection:
        closed = False

        @staticmethod
        def execute(_statement):
            return Result()

        def close(self):
            self.closed = True

    class Engine:
        connection = Connection()

        def connect(self):
            return self.connection

    engine = Engine()
    monkeypatch.setattr(clinical_trials, "ensure_clinical_trials_schema", lambda: None)
    monkeypatch.setattr(clinical_trials, "get_cortellis_engine", lambda: engine)

    result = clinical_trials.sync_clinical_trials("recent")

    assert result == {
        "status": "skipped",
        "reason": "ClinicalTrials.gov sync already running",
        "lane": "recent",
    }
    assert engine.connection.closed is True


def test_unknown_sync_lane_is_rejected_before_schema_or_network_work():
    with pytest.raises(ValueError, match="recent or backfill"):
        clinical_trials.sync_clinical_trials("everything")
