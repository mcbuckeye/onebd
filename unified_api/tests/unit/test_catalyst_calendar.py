"""Tests for grounded catalyst calendar queries and exports."""

from datetime import date

from unified_api.services.catalyst_calendar import (
    ACTIVE_TRIAL_STATUSES,
    CatalystCalendarFilters,
    catalyst_calendar_csv,
    catalyst_calendar_ics,
    fetch_catalyst_calendar,
)


class _Result:
    def __init__(self, *, one=None, all_rows=None):
        self._one = one
        self._all = all_rows or []

    def mappings(self):
        return self

    def one(self):
        return self._one

    def all(self):
        return self._all


class _Session:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def execute(self, statement, params):
        sql = str(statement)
        self.calls.append((sql, params))
        if "COUNT(*) AS total" in sql:
            return _Result(one={
                "total": len(self.rows),
                "estimated_dates": 1,
                "phase_3": 1,
                "linked_to_company": 1,
                "linked_to_drug": 1,
            })
        return _Result(all_rows=self.rows)


def _event():
    return {
        "nct_id": "NCT12345678",
        "brief_title": "Trial, one; pivotal",
        "official_title": "A pivotal trial",
        "overall_status": "RECRUITING",
        "phases": ["PHASE3"],
        "enrollment": 240,
        "catalyst_date": date(2026, 10, 5),
        "catalyst_date_raw": "2026-10",
        "catalyst_date_type": "ESTIMATED",
        "lead_sponsor_name": "Example Bio",
        "conditions": ["Lung Cancer"],
        "interventions": [],
        "last_update_posted": date(2026, 7, 1),
        "source_url": "https://clinicaltrials.gov/study/NCT12345678",
        "linked_companies": [{"id": 7, "name": "Example Bio"}],
        "linked_drugs": [{"id": 8, "name": "ABC-123"}],
        "linked_indications": [{"id": 9, "name": "Lung Cancer"}],
    }


def test_calendar_defaults_to_active_trials_and_preserves_exact_links():
    session = _Session([_event()])
    filters = CatalystCalendarFilters(
        date_from=date(2026, 7, 14),
        date_to=date(2027, 7, 14),
    )

    result = fetch_catalyst_calendar(session, filters, limit=25, offset=10)

    assert result["total"] == 1
    assert result["summary"] == {
        "estimated_dates": 1,
        "phase_3": 1,
        "linked_to_company": 1,
        "linked_to_drug": 1,
    }
    assert result["events"][0]["linked_companies"][0]["id"] == 7
    assert session.calls[0][1]["active_statuses"] == list(ACTIVE_TRIAL_STATUSES)
    assert session.calls[1][1]["limit"] == 25
    assert session.calls[1][1]["offset"] == 10


def test_calendar_uses_bound_exact_entity_and_text_filters():
    session = _Session([])
    filters = CatalystCalendarFilters(
        date_from=date(2026, 1, 1),
        date_to=date(2026, 12, 31),
        status="completed",
        phase="phase2",
        company_id=42,
        drug_id=43,
        indication_id=44,
        query="Example",
        include_inactive=True,
    )

    fetch_catalyst_calendar(session, filters)

    sql, params = session.calls[0]
    assert "company_link.company_id = :company_id" in sql
    assert "drug_link.drug_id = :drug_id" in sql
    assert "indication_link.indication_id = :indication_id" in sql
    assert params["status"] == "COMPLETED"
    assert params["phase"] == '["PHASE2"]'
    assert params["query"] == "%Example%"
    assert "active_statuses" not in params


def test_csv_export_is_analysis_ready_and_retains_source_precision():
    rendered = catalyst_calendar_csv([_event()])

    assert "source_date,date_type,nct_id" in rendered
    assert "2026-10,ESTIMATED,NCT12345678" in rendered
    assert "Example Bio" in rendered
    assert "ABC-123" in rendered
    assert "https://clinicaltrials.gov/study/NCT12345678" in rendered


def test_ical_export_creates_all_day_event_and_escapes_content():
    rendered = catalyst_calendar_ics([_event()])

    assert rendered.startswith("BEGIN:VCALENDAR\r\n")
    assert "DTSTART;VALUE=DATE:20261001\r\n" in rendered
    assert "DTEND;VALUE=DATE:20261101\r\n" in rendered
    assert "UID:NCT12345678-primary-completion@onebd\r\n" in rendered
    assert "SUMMARY:Trial\\, one\\; pivotal\r\n" in rendered
    assert "X-ONEBD-DATE-TYPE:ESTIMATED\r\n" in rendered
    assert "TRANSP:TRANSPARENT\r\n" in rendered
    assert rendered.endswith("END:VCALENDAR\r\n")
