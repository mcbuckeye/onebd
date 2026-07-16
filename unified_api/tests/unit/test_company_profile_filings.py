from types import SimpleNamespace

from unified_api.routers.entities import _get_recent_sec_filings


class _RecordingSession:
    def __init__(self):
        self.statement = ""
        self.params = None

    def execute(self, statement, params):
        self.statement = str(statement)
        self.params = params
        return [
            SimpleNamespace(
                id=330929,
                doc_type="8-K",
                title="8-K",
                filing_date="2026-06-26",
                url="https://www.sec.gov/example",
            )
        ]


def test_recent_sec_filings_project_form_type_and_calendar_date():
    session = _RecordingSession()

    filings = _get_recent_sec_filings(session, 501)

    assert "COALESCE(NULLIF(d.subtype, ''), NULLIF(d.doc_type, '')) AS doc_type" in session.statement
    assert "r.filing_date::date::text AS filing_date" in session.statement
    assert session.params == {"company_id": 501}
    assert filings[0].doc_type == "8-K"
    assert filings[0].filing_date == "2026-06-26"
