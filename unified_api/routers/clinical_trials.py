"""ClinicalTrials.gov inventory, search, and linked-entity endpoints."""

from __future__ import annotations

from datetime import date, timedelta
import json

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import text

from unified_api.services.catalyst_calendar import (
    MAX_EXPORT_ROWS,
    CatalystCalendarFilters,
    catalyst_calendar_csv,
    catalyst_calendar_ics,
    fetch_catalyst_calendar,
)
from unified_api.services.clinical_trials import (
    clinical_trials_status,
    ensure_clinical_trials_schema,
)
from unified_api.services.database import get_cortellis_session


router = APIRouter()


def _calendar_filters(
    *,
    date_from: date | None,
    date_to: date | None,
    status: str | None,
    phase: str | None,
    company_id: int | None,
    drug_id: int | None,
    indication_id: int | None,
    query: str | None,
    include_inactive: bool,
) -> CatalystCalendarFilters:
    start = date_from or date.today()
    end = date_to or start + timedelta(days=365)
    if end < start:
        raise HTTPException(status_code=422, detail="date_to must be on or after date_from")
    if (end - start).days > 1825:
        raise HTTPException(status_code=422, detail="Calendar range cannot exceed 1,825 days")
    return CatalystCalendarFilters(
        date_from=start,
        date_to=end,
        status=status,
        phase=phase,
        company_id=company_id,
        drug_id=drug_id,
        indication_id=indication_id,
        query=query,
        include_inactive=include_inactive,
    )


@router.get("/clinical-trials/status")
async def trial_source_status():
    """Return ingestion cursors, inventory, and entity-link coverage."""
    return clinical_trials_status()


@router.get("/clinical-trials")
async def list_clinical_trials(
    status: str | None = None,
    phase: str | None = None,
    condition: str | None = None,
    drug_id: int | None = None,
    company_id: int | None = None,
    has_results: bool | None = None,
    upcoming_days: int | None = Query(default=None, ge=1, le=1825),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Search current trial records with exact linked-entity filters."""
    ensure_clinical_trials_schema()
    filters: list[str] = []
    params: dict[str, object] = {"limit": limit, "offset": offset}
    if status:
        filters.append("trial.overall_status = :status")
        params["status"] = status.upper()
    if phase:
        filters.append("trial.phases @> CAST(:phase AS JSONB)")
        params["phase"] = json.dumps([phase.upper()])
    if condition:
        filters.append("trial.conditions::TEXT ILIKE :condition")
        params["condition"] = f"%{condition}%"
    if drug_id is not None:
        filters.append("EXISTS (SELECT 1 FROM clinical_trial_drugs link "
                       "WHERE link.nct_id = trial.nct_id AND link.drug_id = :drug_id)")
        params["drug_id"] = drug_id
    if company_id is not None:
        filters.append("EXISTS (SELECT 1 FROM clinical_trial_companies link "
                       "WHERE link.nct_id = trial.nct_id "
                       "AND link.company_id = :company_id)")
        params["company_id"] = company_id
    if has_results is not None:
        filters.append("trial.has_results = :has_results")
        params["has_results"] = has_results
    if upcoming_days is not None:
        filters.append(
            "trial.primary_completion_date BETWEEN CURRENT_DATE "
            "AND CURRENT_DATE + :upcoming_days"
        )
        params["upcoming_days"] = upcoming_days
    where = "WHERE " + " AND ".join(filters) if filters else ""
    with get_cortellis_session() as session:
        total = session.execute(text(f"""
            SELECT COUNT(*) FROM clinical_trials trial {where}
        """), params).scalar_one()
        rows = session.execute(text(f"""
            SELECT trial.nct_id, trial.brief_title, trial.official_title,
                   trial.overall_status, trial.phases, trial.study_type,
                   trial.enrollment, trial.start_date,
                   trial.primary_completion_date, trial.completion_date,
                   trial.last_update_posted, trial.lead_sponsor_name,
                   trial.conditions, trial.interventions, trial.has_results,
                   trial.source_url,
                   (SELECT COUNT(*) FROM clinical_trial_drugs link
                    WHERE link.nct_id = trial.nct_id) AS linked_drugs,
                   (SELECT COUNT(*) FROM clinical_trial_companies link
                    WHERE link.nct_id = trial.nct_id) AS linked_companies
            FROM clinical_trials trial
            {where}
            ORDER BY trial.last_update_posted DESC NULLS LAST, trial.nct_id
            LIMIT :limit OFFSET :offset
        """), params).mappings().all()
    return {
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "trials": [dict(row) for row in rows],
    }


@router.get("/clinical-trials/catalysts")
async def clinical_trial_catalysts(
    upcoming_days: int = Query(default=365, ge=1, le=1825),
    changed_since_days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=100, ge=1, le=500),
):
    """Return completion catalysts, stopped programs, and observed status changes."""
    ensure_clinical_trials_schema()
    params = {
        "upcoming_days": upcoming_days,
        "changed_since_days": changed_since_days,
        "limit": limit,
    }
    with get_cortellis_session() as session:
        upcoming = session.execute(text("""
            SELECT nct_id, brief_title, overall_status, phases,
                   primary_completion_date AS catalyst_date,
                   primary_completion_date_raw AS catalyst_date_precision,
                   lead_sponsor_name, conditions, source_url
            FROM clinical_trials
            WHERE primary_completion_date BETWEEN CURRENT_DATE
                                              AND CURRENT_DATE + :upcoming_days
              AND overall_status IN (
                  'RECRUITING', 'NOT_YET_RECRUITING',
                  'ACTIVE_NOT_RECRUITING', 'ENROLLING_BY_INVITATION'
              )
            ORDER BY primary_completion_date, nct_id
            LIMIT :limit
        """), params).mappings().all()
        stopped = session.execute(text("""
            SELECT nct_id, brief_title, overall_status, why_stopped,
                   last_update_posted, lead_sponsor_name, phases,
                   conditions, source_url
            FROM clinical_trials
            WHERE overall_status IN ('SUSPENDED', 'TERMINATED', 'WITHDRAWN')
              AND last_update_posted >= CURRENT_DATE - :changed_since_days
            ORDER BY last_update_posted DESC, nct_id
            LIMIT :limit
        """), params).mappings().all()
        changes = session.execute(text("""
            SELECT history.nct_id, trial.brief_title,
                   history.previous_status, history.overall_status AS new_status,
                   history.why_stopped, history.source_last_update,
                   history.observed_at, trial.lead_sponsor_name,
                   trial.phases, trial.conditions, trial.source_url
            FROM (
                SELECT nct_id, overall_status, why_stopped,
                       source_last_update, observed_at,
                       LAG(overall_status) OVER (
                           PARTITION BY nct_id
                           ORDER BY source_last_update NULLS FIRST, observed_at, id
                       ) AS previous_status
                FROM clinical_trial_status_history
            ) history
            JOIN clinical_trials trial ON trial.nct_id = history.nct_id
            WHERE history.previous_status IS NOT NULL
              AND history.previous_status IS DISTINCT FROM history.overall_status
              AND history.observed_at >= NOW() - (
                  :changed_since_days * INTERVAL '1 day'
              )
            ORDER BY history.observed_at DESC, history.nct_id
            LIMIT :limit
        """), params).mappings().all()
    return {
        "upcoming_primary_completions": [dict(row) for row in upcoming],
        "recently_stopped_programs": [dict(row) for row in stopped],
        "observed_status_changes": [dict(row) for row in changes],
        "upcoming_days": upcoming_days,
        "changed_since_days": changed_since_days,
        "source": "clinicaltrials.gov_api_v2",
    }


@router.get("/clinical-trials/calendar")
async def clinical_trial_calendar(
    date_from: date | None = None,
    date_to: date | None = None,
    status: str | None = None,
    phase: str | None = None,
    company_id: int | None = None,
    drug_id: int | None = None,
    indication_id: int | None = None,
    q: str | None = Query(default=None, min_length=2, max_length=200),
    include_inactive: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Return a filterable primary-completion calendar with exact entity links."""
    ensure_clinical_trials_schema()
    filters = _calendar_filters(
        date_from=date_from,
        date_to=date_to,
        status=status,
        phase=phase,
        company_id=company_id,
        drug_id=drug_id,
        indication_id=indication_id,
        query=q,
        include_inactive=include_inactive,
    )
    with get_cortellis_session() as session:
        return fetch_catalyst_calendar(session, filters, limit=limit, offset=offset)


@router.get("/clinical-trials/calendar.csv")
async def export_clinical_trial_calendar_csv(
    date_from: date | None = None,
    date_to: date | None = None,
    status: str | None = None,
    phase: str | None = None,
    company_id: int | None = None,
    drug_id: int | None = None,
    indication_id: int | None = None,
    q: str | None = Query(default=None, min_length=2, max_length=200),
    include_inactive: bool = False,
):
    """Export the filtered catalyst calendar as analysis-ready CSV."""
    ensure_clinical_trials_schema()
    filters = _calendar_filters(
        date_from=date_from,
        date_to=date_to,
        status=status,
        phase=phase,
        company_id=company_id,
        drug_id=drug_id,
        indication_id=indication_id,
        query=q,
        include_inactive=include_inactive,
    )
    with get_cortellis_session() as session:
        result = fetch_catalyst_calendar(
            session,
            filters,
            limit=MAX_EXPORT_ROWS,
            offset=0,
        )
    if result["total"] > MAX_EXPORT_ROWS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Export contains {result['total']:,} events; narrow the filters "
                f"to {MAX_EXPORT_ROWS:,} or fewer"
            ),
        )
    filename = f"clinical-trial-catalysts-{filters.date_from}-{filters.date_to}.csv"
    return Response(
        content=catalyst_calendar_csv(result["events"]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/clinical-trials/calendar.ics")
async def export_clinical_trial_calendar_ics(
    date_from: date | None = None,
    date_to: date | None = None,
    status: str | None = None,
    phase: str | None = None,
    company_id: int | None = None,
    drug_id: int | None = None,
    indication_id: int | None = None,
    q: str | None = Query(default=None, min_length=2, max_length=200),
    include_inactive: bool = False,
):
    """Export the filtered catalyst calendar for Outlook, Google, or Apple Calendar."""
    ensure_clinical_trials_schema()
    filters = _calendar_filters(
        date_from=date_from,
        date_to=date_to,
        status=status,
        phase=phase,
        company_id=company_id,
        drug_id=drug_id,
        indication_id=indication_id,
        query=q,
        include_inactive=include_inactive,
    )
    with get_cortellis_session() as session:
        result = fetch_catalyst_calendar(
            session,
            filters,
            limit=MAX_EXPORT_ROWS,
            offset=0,
        )
    if result["total"] > MAX_EXPORT_ROWS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Export contains {result['total']:,} events; narrow the filters "
                f"to {MAX_EXPORT_ROWS:,} or fewer"
            ),
        )
    filename = f"clinical-trial-catalysts-{filters.date_from}-{filters.date_to}.ics"
    return Response(
        content=catalyst_calendar_ics(result["events"]),
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/clinical-trials/{nct_id}")
async def clinical_trial_detail(nct_id: str):
    """Return the lossless current record, history, and exact entity links."""
    ensure_clinical_trials_schema()
    nct_id = nct_id.upper()
    with get_cortellis_session() as session:
        trial = session.execute(text("""
            SELECT * FROM clinical_trials WHERE nct_id = :nct_id
        """), {"nct_id": nct_id}).mappings().first()
        if not trial:
            raise HTTPException(status_code=404, detail="Clinical trial not found")
        statuses = session.execute(text("""
            SELECT overall_status, why_stopped, source_last_update, observed_at
            FROM clinical_trial_status_history
            WHERE nct_id = :nct_id
            ORDER BY source_last_update, observed_at
        """), {"nct_id": nct_id}).mappings().all()
        drugs = session.execute(text("""
            SELECT link.drug_id, drug.name_display, link.intervention_name,
                   link.matched_alias, link.match_method, link.confidence
            FROM clinical_trial_drugs link
            JOIN drugs drug ON drug.id = link.drug_id
            WHERE link.nct_id = :nct_id
            ORDER BY drug.name_display
        """), {"nct_id": nct_id}).mappings().all()
        companies = session.execute(text("""
            SELECT link.company_id, company.name, link.organization_name,
                   link.organization_role, link.matched_alias,
                   link.match_method, link.confidence
            FROM clinical_trial_companies link
            JOIN companies company ON company.id = link.company_id
            WHERE link.nct_id = :nct_id
            ORDER BY link.organization_role, company.name
        """), {"nct_id": nct_id}).mappings().all()
        indications = session.execute(text("""
            SELECT link.indication_id, indication.name, link.condition_name,
                   link.match_method, link.confidence
            FROM clinical_trial_indications link
            JOIN indications indication ON indication.id = link.indication_id
            WHERE link.nct_id = :nct_id
            ORDER BY indication.name
        """), {"nct_id": nct_id}).mappings().all()
        versions = session.execute(text("""
            SELECT COUNT(*) FROM clinical_trial_response_history
            WHERE nct_id = :nct_id
        """), {"nct_id": nct_id}).scalar_one()
    return {
        "trial": dict(trial),
        "status_history": [dict(row) for row in statuses],
        "linked_drugs": [dict(row) for row in drugs],
        "linked_companies": [dict(row) for row in companies],
        "linked_indications": [dict(row) for row in indications],
        "retained_source_versions": int(versions),
    }
