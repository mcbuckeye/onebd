"""Grounded clinical-trial catalyst calendar queries and exports."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from io import StringIO
import json
from typing import Any

from sqlalchemy import text


ACTIVE_TRIAL_STATUSES = (
    "RECRUITING",
    "NOT_YET_RECRUITING",
    "ACTIVE_NOT_RECRUITING",
    "ENROLLING_BY_INVITATION",
)
MAX_EXPORT_ROWS = 50_000


@dataclass(frozen=True)
class CatalystCalendarFilters:
    """Validated filters for primary-completion catalyst events."""

    date_from: date
    date_to: date
    status: str | None = None
    phase: str | None = None
    company_id: int | None = None
    drug_id: int | None = None
    indication_id: int | None = None
    query: str | None = None
    include_inactive: bool = False


def _where_clause(filters: CatalystCalendarFilters) -> tuple[str, dict[str, Any]]:
    conditions = [
        "trial.primary_completion_date BETWEEN :date_from AND :date_to",
    ]
    params: dict[str, Any] = {
        "date_from": filters.date_from,
        "date_to": filters.date_to,
    }
    if filters.status:
        conditions.append("trial.overall_status = :status")
        params["status"] = filters.status.upper()
    elif not filters.include_inactive:
        conditions.append("trial.overall_status = ANY(CAST(:active_statuses AS TEXT[]))")
        params["active_statuses"] = list(ACTIVE_TRIAL_STATUSES)
    if filters.phase:
        conditions.append("trial.phases @> CAST(:phase AS JSONB)")
        params["phase"] = json.dumps([filters.phase.upper()])
    if filters.company_id is not None:
        conditions.append("""
            EXISTS (
                SELECT 1 FROM clinical_trial_companies company_link
                WHERE company_link.nct_id = trial.nct_id
                  AND company_link.company_id = :company_id
            )
        """)
        params["company_id"] = filters.company_id
    if filters.drug_id is not None:
        conditions.append("""
            EXISTS (
                SELECT 1 FROM clinical_trial_drugs drug_link
                WHERE drug_link.nct_id = trial.nct_id
                  AND drug_link.drug_id = :drug_id
            )
        """)
        params["drug_id"] = filters.drug_id
    if filters.indication_id is not None:
        conditions.append("""
            EXISTS (
                SELECT 1 FROM clinical_trial_indications indication_link
                WHERE indication_link.nct_id = trial.nct_id
                  AND indication_link.indication_id = :indication_id
            )
        """)
        params["indication_id"] = filters.indication_id
    if filters.query:
        conditions.append("""
            (
                trial.brief_title ILIKE :query
                OR trial.official_title ILIKE :query
                OR trial.lead_sponsor_name ILIKE :query
                OR trial.conditions::TEXT ILIKE :query
                OR trial.interventions::TEXT ILIKE :query
                OR trial.nct_id ILIKE :query
            )
        """)
        params["query"] = f"%{filters.query.strip()}%"
    return " AND ".join(conditions), params


def fetch_catalyst_calendar(
    session,
    filters: CatalystCalendarFilters,
    *,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Fetch a paginated catalyst calendar with exact entity links."""
    where, params = _where_clause(filters)
    summary = session.execute(text(f"""
        SELECT COUNT(*) AS total,
               COUNT(*) FILTER (
                   WHERE trial.primary_completion_date_type = 'ESTIMATED'
               ) AS estimated_dates,
               COUNT(*) FILTER (
                   WHERE trial.phases @> '["PHASE3"]'::JSONB
               ) AS phase_3,
               COUNT(*) FILTER (
                   WHERE EXISTS (
                       SELECT 1 FROM clinical_trial_companies company_link
                       WHERE company_link.nct_id = trial.nct_id
                   )
               ) AS linked_to_company,
               COUNT(*) FILTER (
                   WHERE EXISTS (
                       SELECT 1 FROM clinical_trial_drugs drug_link
                       WHERE drug_link.nct_id = trial.nct_id
                   )
               ) AS linked_to_drug
        FROM clinical_trials trial
        WHERE {where}
    """), params).mappings().one()

    row_params = {**params, "limit": limit, "offset": offset}
    rows = session.execute(text(f"""
        SELECT trial.nct_id,
               trial.brief_title,
               trial.official_title,
               trial.overall_status,
               trial.phases,
               trial.enrollment,
               trial.primary_completion_date AS catalyst_date,
               trial.primary_completion_date_raw AS catalyst_date_raw,
               trial.primary_completion_date_type AS catalyst_date_type,
               trial.lead_sponsor_name,
               trial.conditions,
               trial.interventions,
               trial.last_update_posted,
               trial.source_url,
               COALESCE(company_links.items, '[]'::JSONB) AS linked_companies,
               COALESCE(drug_links.items, '[]'::JSONB) AS linked_drugs,
               COALESCE(indication_links.items, '[]'::JSONB) AS linked_indications
        FROM clinical_trials trial
        LEFT JOIN LATERAL (
            SELECT JSONB_AGG(item ORDER BY item->>'name') AS items
            FROM (
                SELECT DISTINCT JSONB_BUILD_OBJECT(
                    'id', company.id,
                    'name', company.name,
                    'match_method', link.match_method,
                    'confidence', link.confidence
                ) AS item
                FROM clinical_trial_companies link
                JOIN companies company ON company.id = link.company_id
                WHERE link.nct_id = trial.nct_id
            ) exact_companies
        ) company_links ON TRUE
        LEFT JOIN LATERAL (
            SELECT JSONB_AGG(item ORDER BY item->>'name') AS items
            FROM (
                SELECT DISTINCT JSONB_BUILD_OBJECT(
                    'id', drug.id,
                    'name', drug.name_display,
                    'match_method', link.match_method,
                    'confidence', link.confidence
                ) AS item
                FROM clinical_trial_drugs link
                JOIN drugs drug ON drug.id = link.drug_id
                WHERE link.nct_id = trial.nct_id
            ) exact_drugs
        ) drug_links ON TRUE
        LEFT JOIN LATERAL (
            SELECT JSONB_AGG(item ORDER BY item->>'name') AS items
            FROM (
                SELECT DISTINCT JSONB_BUILD_OBJECT(
                    'id', indication.id,
                    'name', indication.name,
                    'match_method', link.match_method,
                    'confidence', link.confidence
                ) AS item
                FROM clinical_trial_indications link
                JOIN indications indication ON indication.id = link.indication_id
                WHERE link.nct_id = trial.nct_id
            ) exact_indications
        ) indication_links ON TRUE
        WHERE {where}
        ORDER BY trial.primary_completion_date, trial.nct_id
        LIMIT :limit OFFSET :offset
    """), row_params).mappings().all()

    return {
        "total": int(summary["total"] or 0),
        "limit": limit,
        "offset": offset,
        "summary": {
            "estimated_dates": int(summary["estimated_dates"] or 0),
            "phase_3": int(summary["phase_3"] or 0),
            "linked_to_company": int(summary["linked_to_company"] or 0),
            "linked_to_drug": int(summary["linked_to_drug"] or 0),
        },
        "events": [dict(row) for row in rows],
        "date_from": filters.date_from,
        "date_to": filters.date_to,
        "source": "clinicaltrials.gov_api_v2",
        "methodology": (
            "Primary completion dates reported by ClinicalTrials.gov. "
            "Company, drug, and indication associations are exact normalized "
            "links; source date precision and estimated/actual labels are retained."
        ),
    }


def catalyst_calendar_csv(events: list[dict[str, Any]]) -> str:
    """Serialize catalyst events to analysis-ready CSV."""
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([
        "catalyst_date",
        "source_date",
        "date_type",
        "nct_id",
        "title",
        "status",
        "phases",
        "lead_sponsor",
        "enrollment",
        "conditions",
        "linked_companies",
        "linked_drugs",
        "linked_indications",
        "last_update_posted",
        "source_url",
    ])
    for event in events:
        writer.writerow([
            event.get("catalyst_date") or "",
            event.get("catalyst_date_raw") or "",
            event.get("catalyst_date_type") or "",
            event.get("nct_id") or "",
            event.get("brief_title") or "",
            event.get("overall_status") or "",
            "; ".join(event.get("phases") or []),
            event.get("lead_sponsor_name") or "",
            event.get("enrollment") or "",
            "; ".join(event.get("conditions") or []),
            _linked_names(event.get("linked_companies")),
            _linked_names(event.get("linked_drugs")),
            _linked_names(event.get("linked_indications")),
            event.get("last_update_posted") or "",
            event.get("source_url") or "",
        ])
    return output.getvalue()


def _linked_names(items: Any) -> str:
    if not isinstance(items, list):
        return ""
    return "; ".join(str(item.get("name")) for item in items if item.get("name"))


def _ical_escape(value: Any) -> str:
    return (
        str(value or "")
        .replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace(";", "\\;")
        .replace(",", "\\,")
    )


def catalyst_calendar_ics(events: list[dict[str, Any]]) -> str:
    """Serialize catalyst events as all-day RFC 5545 calendar entries."""
    generated_at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//OneBD//Clinical Trial Catalyst Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:OneBD Clinical Trial Catalysts",
    ]
    for event in events:
        catalyst_date = event.get("catalyst_date")
        if not catalyst_date:
            continue
        if isinstance(catalyst_date, str):
            catalyst_date = date.fromisoformat(catalyst_date)
        source_date = str(event.get("catalyst_date_raw") or "")
        event_start = catalyst_date
        event_end = catalyst_date + timedelta(days=1)
        precision_label = "date"
        if len(source_date) == 4 and source_date.isdigit():
            event_start = date(int(source_date), 1, 1)
            event_end = date(int(source_date) + 1, 1, 1)
            precision_label = "year only"
        elif (
            len(source_date) == 7
            and source_date[4] == "-"
            and source_date[:4].isdigit()
            and source_date[5:].isdigit()
        ):
            source_year, source_month = (int(value) for value in source_date.split("-"))
            event_start = date(source_year, source_month, 1)
            if source_month == 12:
                event_end = date(source_year + 1, 1, 1)
            else:
                event_end = date(source_year, source_month + 1, 1)
            precision_label = "month only"
        phases = ", ".join(event.get("phases") or []) or "Phase not reported"
        linked = _linked_names(event.get("linked_companies"))
        description = (
            f"Status: {event.get('overall_status') or 'Not reported'}\n"
            f"Phase: {phases}\n"
            f"Sponsor: {event.get('lead_sponsor_name') or 'Not reported'}\n"
            f"Source-reported date: {source_date or catalyst_date} "
            f"({precision_label}; {event.get('catalyst_date_type') or 'type not reported'})"
        )
        if linked:
            description += f"\nExact-linked companies: {linked}"
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{event.get('nct_id')}-primary-completion@onebd",
            f"DTSTAMP:{generated_at}",
            f"DTSTART;VALUE=DATE:{event_start.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{event_end.strftime('%Y%m%d')}",
            f"SUMMARY:{_ical_escape(event.get('brief_title') or event.get('nct_id'))}",
            f"DESCRIPTION:{_ical_escape(description)}",
            f"URL:{_ical_escape(event.get('source_url'))}",
            "CATEGORIES:Clinical Trial,Primary Completion",
            "TRANSP:TRANSPARENT",
            f"X-ONEBD-NCT-ID:{event.get('nct_id')}",
            f"X-ONEBD-DATE-TYPE:{_ical_escape(event.get('catalyst_date_type'))}",
            f"X-ONEBD-SOURCE-DATE:{_ical_escape(event.get('catalyst_date_raw'))}",
            "END:VEVENT",
        ])
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
