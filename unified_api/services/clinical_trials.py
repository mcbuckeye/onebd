"""Durable ClinicalTrials.gov API v2 ingestion and exact entity linking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import re
from typing import Any
from urllib.error import HTTPError
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from sqlalchemy import text

from unified_api.config import settings
from unified_api.services.database import (
    get_cortellis_engine,
    get_cortellis_session,
)
from unified_api.services.entity_resolution import (
    EntityResolutionService,
    normalize_identifier_value,
)
from unified_api.services.public_source_http import (
    PublicSourceHttpClient,
    RetryPolicy,
)


CLINICALTRIALS_SOURCE = "clinicaltrials.gov_api_v2"
CLINICALTRIALS_SCHEMA_VERSION = 1
BACKFILL_START_DATE = date(1900, 1, 1)
_clinical_trials_schema_ready = False


@dataclass(frozen=True)
class ClinicalTrialsPage:
    studies: list[dict[str, Any]]
    next_page_token: str | None
    total_count: int | None


class ClinicalTrialsClient:
    """Small retrying client for the official ClinicalTrials.gov API v2."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout: float = 30,
        delay_seconds: float = 0.15,
        max_retries: int = 3,
    ):
        self.base_url = (base_url or settings.clinicaltrials_base_url).rstrip("/")
        self.timeout = timeout
        self.delay_seconds = delay_seconds
        self.max_retries = max_retries
        self._http = PublicSourceHttpClient(
            source=CLINICALTRIALS_SOURCE,
            base_url=self.base_url,
            user_agent=settings.clinicaltrials_user_agent,
            timeout=timeout,
            min_interval_seconds=delay_seconds,
            retry_policy=RetryPolicy(max_retries=max_retries),
            opener=urlopen,
        )

    def _get_json(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = self._http.get_json(path, params)
        if response is None:  # This client never treats 404 as an empty result.
            raise RuntimeError("ClinicalTrials.gov returned no response")
        return response.payload

    def dataset_version(self) -> dict[str, Any]:
        return self._get_json("/version")

    def updated_studies(
        self,
        *,
        start_date: date,
        end_date: date,
        page_size: int,
        page_token: str | None = None,
    ) -> ClinicalTrialsPage:
        page_size = max(1, min(1000, int(page_size)))
        query = (
            "AREA[LastUpdatePostDate]"
            f"RANGE[{start_date.isoformat()}, {end_date.isoformat()}]"
        )
        payload = self._get_json("/studies", {
            "query.term": query,
            "format": "json",
            "pageSize": page_size,
            "pageToken": page_token,
            "countTotal": "true",
            "sort": "LastUpdatePostDate:asc",
        })
        studies = payload.get("studies") or []
        if not isinstance(studies, list):
            raise ValueError("ClinicalTrials.gov returned a non-list studies payload")
        return ClinicalTrialsPage(
            studies=[study for study in studies if isinstance(study, dict)],
            next_page_token=payload.get("nextPageToken"),
            total_count=(
                int(payload["totalCount"])
                if payload.get("totalCount") is not None else None
            ),
        )


def _updated_studies_page_with_token_recovery(
    client: ClinicalTrialsClient,
    *,
    start_date: date,
    end_date: date,
    page_size: int,
    page_token: str | None,
) -> tuple[ClinicalTrialsPage, bool]:
    """Restart a page chain once when the source rejects a stale token."""
    try:
        return client.updated_studies(
            start_date=start_date,
            end_date=end_date,
            page_size=page_size,
            page_token=page_token,
        ), False
    except HTTPError as exc:
        if exc.code != 400 or not page_token:
            raise
        return client.updated_studies(
            start_date=start_date,
            end_date=end_date,
            page_size=page_size,
            page_token=None,
        ), True


def _dataset_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("America/New_York"))
    return parsed.astimezone(timezone.utc)


def _normalized_date(value: Any) -> tuple[date | None, str | None]:
    """Return a sortable date plus the exact source precision string."""
    raw = str(value or "").strip()
    if not raw:
        return None, None
    for pattern, suffix in ((r"^\d{4}$", "-01-01"), (r"^\d{4}-\d{2}$", "-01")):
        if re.match(pattern, raw):
            raw_date = f"{raw}{suffix}"
            return date.fromisoformat(raw_date), raw
    try:
        return date.fromisoformat(raw[:10]), raw
    except ValueError:
        return None, raw


def _date_struct(module: dict[str, Any], key: str) -> tuple[date | None, str | None, str | None]:
    value = module.get(key) or {}
    if not isinstance(value, dict):
        return None, None, None
    parsed, raw = _normalized_date(value.get("date"))
    return parsed, raw, value.get("type")


def _study_fields(study: dict[str, Any]) -> dict[str, Any]:
    protocol = study.get("protocolSection") or {}
    identification = protocol.get("identificationModule") or {}
    status = protocol.get("statusModule") or {}
    design = protocol.get("designModule") or {}
    sponsor = protocol.get("sponsorCollaboratorsModule") or {}
    conditions = protocol.get("conditionsModule") or {}
    arms = protocol.get("armsInterventionsModule") or {}
    outcomes = protocol.get("outcomesModule") or {}
    locations = protocol.get("contactsLocationsModule") or {}
    enrollment = design.get("enrollmentInfo") or {}
    lead_sponsor = sponsor.get("leadSponsor") or {}

    nct_id = identification.get("nctId")
    if not nct_id or not re.fullmatch(r"NCT\d{8}", str(nct_id)):
        raise ValueError("ClinicalTrials.gov study omitted a valid NCT ID")

    start_date, start_raw, start_type = _date_struct(status, "startDateStruct")
    primary_date, primary_raw, primary_type = _date_struct(
        status, "primaryCompletionDateStruct"
    )
    completion_date, completion_raw, completion_type = _date_struct(
        status, "completionDateStruct"
    )
    update_date, update_raw, _ = _date_struct(status, "lastUpdatePostDateStruct")

    return {
        "nct_id": str(nct_id),
        "brief_title": identification.get("briefTitle"),
        "official_title": identification.get("officialTitle"),
        "acronym": identification.get("acronym"),
        "overall_status": status.get("overallStatus") or "UNKNOWN",
        "why_stopped": status.get("whyStopped"),
        "study_type": design.get("studyType"),
        "phases": design.get("phases") or [],
        "enrollment": enrollment.get("count"),
        "enrollment_type": enrollment.get("type"),
        "start_date": start_date,
        "start_date_raw": start_raw,
        "start_date_type": start_type,
        "primary_completion_date": primary_date,
        "primary_completion_date_raw": primary_raw,
        "primary_completion_date_type": primary_type,
        "completion_date": completion_date,
        "completion_date_raw": completion_raw,
        "completion_date_type": completion_type,
        "last_update_posted": update_date,
        "last_update_posted_raw": update_raw,
        "lead_sponsor_name": lead_sponsor.get("name"),
        "lead_sponsor_class": lead_sponsor.get("class"),
        "collaborators": sponsor.get("collaborators") or [],
        "conditions": conditions.get("conditions") or [],
        "keywords": conditions.get("keywords") or [],
        "interventions": arms.get("interventions") or [],
        "primary_outcomes": outcomes.get("primaryOutcomes") or [],
        "secondary_outcomes": outcomes.get("secondaryOutcomes") or [],
        "locations": locations.get("locations") or [],
        "has_results": bool(study.get("resultsSection")),
    }


def ensure_clinical_trials_schema() -> None:
    """Create normalized/current, history, link, and checkpoint tables."""
    global _clinical_trials_schema_ready
    if _clinical_trials_schema_ready:
        return
    from unified_api.services.runtime_schema import runtime_schema_is_pre_migrated

    if runtime_schema_is_pre_migrated():
        _clinical_trials_schema_ready = True
        return
    EntityResolutionService().ensure_identity_schema()
    with get_cortellis_session() as session:
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS clinical_trials (
                nct_id VARCHAR(11) PRIMARY KEY,
                brief_title TEXT,
                official_title TEXT,
                acronym VARCHAR(255),
                overall_status VARCHAR(50) NOT NULL,
                why_stopped TEXT,
                study_type VARCHAR(50),
                phases JSONB NOT NULL DEFAULT '[]'::jsonb,
                enrollment INTEGER,
                enrollment_type VARCHAR(30),
                start_date DATE,
                start_date_raw VARCHAR(20),
                start_date_type VARCHAR(30),
                primary_completion_date DATE,
                primary_completion_date_raw VARCHAR(20),
                primary_completion_date_type VARCHAR(30),
                completion_date DATE,
                completion_date_raw VARCHAR(20),
                completion_date_type VARCHAR(30),
                last_update_posted DATE,
                last_update_posted_raw VARCHAR(20),
                lead_sponsor_name TEXT,
                lead_sponsor_class VARCHAR(50),
                collaborators JSONB NOT NULL DEFAULT '[]'::jsonb,
                conditions JSONB NOT NULL DEFAULT '[]'::jsonb,
                keywords JSONB NOT NULL DEFAULT '[]'::jsonb,
                interventions JSONB NOT NULL DEFAULT '[]'::jsonb,
                primary_outcomes JSONB NOT NULL DEFAULT '[]'::jsonb,
                secondary_outcomes JSONB NOT NULL DEFAULT '[]'::jsonb,
                locations JSONB NOT NULL DEFAULT '[]'::jsonb,
                has_results BOOLEAN NOT NULL DEFAULT FALSE,
                source VARCHAR(100) NOT NULL,
                source_url TEXT NOT NULL,
                raw_sha256 CHAR(64) NOT NULL,
                raw_payload JSONB NOT NULL,
                schema_version INTEGER NOT NULL,
                first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_clinical_trials_update
            ON clinical_trials (last_update_posted DESC, nct_id)
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_clinical_trials_status_phase
            ON clinical_trials (overall_status, primary_completion_date)
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_clinical_trials_conditions
            ON clinical_trials USING GIN (conditions)
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS clinical_trial_response_history (
                id BIGSERIAL PRIMARY KEY,
                nct_id VARCHAR(11) NOT NULL REFERENCES clinical_trials(nct_id)
                    ON DELETE CASCADE,
                response_sha256 CHAR(64) NOT NULL,
                raw_payload JSONB NOT NULL,
                first_fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (nct_id, response_sha256)
            )
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS clinical_trial_status_history (
                id BIGSERIAL PRIMARY KEY,
                nct_id VARCHAR(11) NOT NULL REFERENCES clinical_trials(nct_id)
                    ON DELETE CASCADE,
                overall_status VARCHAR(50) NOT NULL,
                why_stopped TEXT,
                source_last_update DATE,
                observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        session.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_clinical_trial_status_history
            ON clinical_trial_status_history (
                nct_id,
                overall_status,
                COALESCE(source_last_update, DATE '0001-01-01')
            )
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS clinical_trial_drugs (
                nct_id VARCHAR(11) NOT NULL REFERENCES clinical_trials(nct_id)
                    ON DELETE CASCADE,
                drug_id INTEGER NOT NULL REFERENCES drugs(id) ON DELETE CASCADE,
                intervention_name TEXT NOT NULL,
                intervention_name_hash CHAR(64) NOT NULL,
                matched_alias TEXT NOT NULL,
                match_method VARCHAR(50) NOT NULL,
                confidence FLOAT NOT NULL,
                source VARCHAR(100) NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (nct_id, drug_id, intervention_name_hash)
            )
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_clinical_trial_drugs_drug
            ON clinical_trial_drugs (drug_id, nct_id)
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS clinical_trial_companies (
                nct_id VARCHAR(11) NOT NULL REFERENCES clinical_trials(nct_id)
                    ON DELETE CASCADE,
                company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                organization_name TEXT NOT NULL,
                organization_name_hash CHAR(64) NOT NULL,
                organization_role VARCHAR(30) NOT NULL,
                matched_alias TEXT NOT NULL,
                match_method VARCHAR(50) NOT NULL,
                confidence FLOAT NOT NULL,
                source VARCHAR(100) NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (
                    nct_id, company_id, organization_name_hash, organization_role
                )
            )
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_clinical_trial_companies_company
            ON clinical_trial_companies (company_id, nct_id)
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS clinical_trial_indications (
                nct_id VARCHAR(11) NOT NULL REFERENCES clinical_trials(nct_id)
                    ON DELETE CASCADE,
                indication_id INTEGER NOT NULL REFERENCES indications(id)
                    ON DELETE CASCADE,
                condition_name TEXT NOT NULL,
                condition_name_hash CHAR(64) NOT NULL,
                match_method VARCHAR(50) NOT NULL,
                confidence FLOAT NOT NULL,
                source VARCHAR(100) NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (nct_id, indication_id, condition_name_hash)
            )
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS clinical_trials_sync_state (
                lane VARCHAR(20) PRIMARY KEY,
                window_start DATE,
                window_end DATE,
                next_page_token TEXT,
                dataset_timestamp TIMESTAMPTZ,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                pages_processed BIGINT NOT NULL DEFAULT 0,
                studies_processed BIGINT NOT NULL DEFAULT 0,
                last_error TEXT,
                last_started_at TIMESTAMPTZ,
                last_completed_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
    _clinical_trials_schema_ready = True


def _unique_drug_alias_match(matches: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return one drug only when an exact alias is unambiguous across drugs."""
    by_drug: dict[int, dict[str, Any]] = {}
    for match in matches:
        drug_id = int(match["drug_id"])
        current = by_drug.get(drug_id)
        if current is None or float(match["confidence"]) > float(current["confidence"]):
            by_drug[drug_id] = match
    if len(by_drug) != 1:
        return None
    return next(iter(by_drug.values()))


def reconcile_clinical_trial_drug_links() -> dict[str, Any]:
    """Remove historical links whose exact alias is missing or cross-drug ambiguous."""
    ensure_clinical_trials_schema()
    lock = get_cortellis_engine().connect()
    acquired = bool(lock.execute(text(
        "SELECT pg_try_advisory_lock(hashtext('onebd_clinical_trials_sync'))"
    )).scalar())
    if not acquired:
        lock.close()
        return {
            "status": "skipped",
            "reason": "ClinicalTrials.gov sync already running",
        }
    try:
        with get_cortellis_session() as session:
            before = int(session.execute(text("""
                SELECT COUNT(*) FROM clinical_trial_drugs
                WHERE source = :source
            """), {"source": CLINICALTRIALS_SOURCE}).scalar() or 0)
            deleted = session.execute(text("""
                WITH alias_resolution AS (
                    SELECT normalized_value,
                           COUNT(DISTINCT drug_id) AS choices,
                           MIN(drug_id) AS only_drug_id
                    FROM drug_aliases
                    WHERE confidence >= 0.7
                    GROUP BY normalized_value
                )
                DELETE FROM clinical_trial_drugs link
                WHERE link.source = :source
                  AND NOT EXISTS (
                    SELECT 1 FROM alias_resolution resolution
                    WHERE resolution.normalized_value = LOWER(
                        REGEXP_REPLACE(TRIM(link.intervention_name),
                                       '\\s+', ' ', 'g')
                    )
                      AND resolution.choices = 1
                      AND resolution.only_drug_id = link.drug_id
                  )
            """), {"source": CLINICALTRIALS_SOURCE}).rowcount
            promoted = session.execute(text("""
                UPDATE clinical_trial_drugs
                SET match_method = 'normalized_exact_unique_alias'
                WHERE source = :source
                  AND match_method IS DISTINCT FROM 'normalized_exact_unique_alias'
            """), {"source": CLINICALTRIALS_SOURCE}).rowcount
            after = int(session.execute(text("""
                SELECT COUNT(*) FROM clinical_trial_drugs
                WHERE source = :source
            """), {"source": CLINICALTRIALS_SOURCE}).scalar() or 0)
        return {
            "status": "completed",
            "before": before,
            "deleted_unverifiable_or_ambiguous": int(deleted or 0),
            "promoted_unique_exact": int(promoted or 0),
            "retained": after,
        }
    finally:
        try:
            lock.execute(text(
                "SELECT pg_advisory_unlock(hashtext('onebd_clinical_trials_sync'))"
            ))
        finally:
            lock.close()


def _link_study_entities(session, fields: dict[str, Any]) -> int:
    nct_id = fields["nct_id"]
    relationships = 0
    session.execute(text("DELETE FROM clinical_trial_drugs WHERE nct_id = :nct_id"), {
        "nct_id": nct_id,
    })
    for intervention in fields["interventions"]:
        if not isinstance(intervention, dict) or intervention.get("type") not in {
            "DRUG", "BIOLOGICAL", "COMBINATION_PRODUCT", "GENETIC"
        }:
            continue
        names = [intervention.get("name"), *(intervention.get("otherNames") or [])]
        for name in dict.fromkeys(str(value).strip() for value in names if value):
            normalized = normalize_identifier_value("drug_alias", name)
            matches = session.execute(text("""
                SELECT DISTINCT drug_id, alias_value, confidence
                FROM drug_aliases
                WHERE normalized_value = :normalized
                  AND confidence >= 0.7
            """), {"normalized": normalized}).mappings().all()
            match = _unique_drug_alias_match([dict(row) for row in matches])
            if match is None:
                continue
            inserted = session.execute(text("""
                INSERT INTO clinical_trial_drugs (
                    nct_id, drug_id, intervention_name,
                    intervention_name_hash, matched_alias, match_method,
                    confidence, source
                ) VALUES (
                    :nct_id, :drug_id, :name, :name_hash, :alias,
                    'normalized_exact_unique_alias', :confidence, :source
                ) ON CONFLICT DO NOTHING RETURNING nct_id
            """), {
                "nct_id": nct_id,
                "drug_id": match["drug_id"],
                "name": name,
                "name_hash": hashlib.sha256(name.encode()).hexdigest(),
                "alias": match["alias_value"],
                "confidence": match["confidence"],
                "source": CLINICALTRIALS_SOURCE,
            }).scalar()
            relationships += int(inserted is not None)

    session.execute(text("DELETE FROM clinical_trial_companies WHERE nct_id = :nct_id"), {
        "nct_id": nct_id,
    })
    organizations = [
        (fields.get("lead_sponsor_name"), "lead_sponsor"),
        *[
            (collaborator.get("name"), "collaborator")
            for collaborator in fields["collaborators"]
            if isinstance(collaborator, dict)
        ],
    ]
    for organization_name, role in organizations:
        if not organization_name:
            continue
        matches = session.execute(text("""
            SELECT DISTINCT xref.cortellis_id AS company_id,
                            alias.alias_value, alias.confidence
            FROM company_aliases alias
            JOIN company_xref xref ON xref.id = alias.xref_id
            WHERE alias.normalized_value = LOWER(
                REGEXP_REPLACE(:organization_name, '[^[:alnum:]]+', '', 'g')
            )
              AND xref.cortellis_id IS NOT NULL
              AND alias.confidence >= 0.8
        """), {"organization_name": organization_name}).mappings().all()
        for match in matches:
            inserted = session.execute(text("""
                INSERT INTO clinical_trial_companies (
                    nct_id, company_id, organization_name,
                    organization_name_hash, organization_role, matched_alias,
                    match_method, confidence, source
                ) VALUES (
                    :nct_id, :company_id, :name, :name_hash, :role, :alias,
                    'normalized_exact', :confidence, :source
                ) ON CONFLICT DO NOTHING RETURNING nct_id
            """), {
                "nct_id": nct_id,
                "company_id": match["company_id"],
                "name": organization_name,
                "name_hash": hashlib.sha256(organization_name.encode()).hexdigest(),
                "role": role,
                "alias": match["alias_value"],
                "confidence": match["confidence"],
                "source": CLINICALTRIALS_SOURCE,
            }).scalar()
            relationships += int(inserted is not None)

    session.execute(text("DELETE FROM clinical_trial_indications WHERE nct_id = :nct_id"), {
        "nct_id": nct_id,
    })
    for condition in dict.fromkeys(str(value).strip() for value in fields["conditions"] if value):
        matches = session.execute(text("""
            SELECT id FROM indications
            WHERE LOWER(REGEXP_REPLACE(name, '[^[:alnum:]]+', '', 'g')) = LOWER(
                REGEXP_REPLACE(:condition, '[^[:alnum:]]+', '', 'g')
            )
        """), {"condition": condition}).scalars().all()
        for indication_id in matches:
            inserted = session.execute(text("""
                INSERT INTO clinical_trial_indications (
                    nct_id, indication_id, condition_name, condition_name_hash,
                    match_method, confidence, source
                ) VALUES (
                    :nct_id, :indication_id, :condition, :condition_hash,
                    'normalized_exact', 1.0, :source
                ) ON CONFLICT DO NOTHING RETURNING nct_id
            """), {
                "nct_id": nct_id,
                "indication_id": indication_id,
                "condition": condition,
                "condition_hash": hashlib.sha256(condition.encode()).hexdigest(),
                "source": CLINICALTRIALS_SOURCE,
            }).scalar()
            relationships += int(inserted is not None)
    return relationships


def _upsert_study(session, study: dict[str, Any]) -> dict[str, int]:
    fields = _study_fields(study)
    raw_json = json.dumps(study, sort_keys=True, separators=(",", ":"))
    raw_sha256 = hashlib.sha256(raw_json.encode()).hexdigest()
    existing = session.execute(text("""
        SELECT raw_sha256, overall_status FROM clinical_trials WHERE nct_id = :nct_id
    """), {"nct_id": fields["nct_id"]}).mappings().first()
    params = {
        **fields,
        "phases": json.dumps(fields["phases"]),
        "collaborators": json.dumps(fields["collaborators"]),
        "conditions": json.dumps(fields["conditions"]),
        "keywords": json.dumps(fields["keywords"]),
        "interventions": json.dumps(fields["interventions"]),
        "primary_outcomes": json.dumps(fields["primary_outcomes"]),
        "secondary_outcomes": json.dumps(fields["secondary_outcomes"]),
        "locations": json.dumps(fields["locations"]),
        "source": CLINICALTRIALS_SOURCE,
        "source_url": f"https://clinicaltrials.gov/study/{fields['nct_id']}",
        "raw_sha256": raw_sha256,
        "raw_payload": raw_json,
        "schema_version": CLINICALTRIALS_SCHEMA_VERSION,
    }
    session.execute(text("""
        INSERT INTO clinical_trials (
            nct_id, brief_title, official_title, acronym, overall_status,
            why_stopped, study_type, phases, enrollment, enrollment_type,
            start_date, start_date_raw, start_date_type,
            primary_completion_date, primary_completion_date_raw,
            primary_completion_date_type, completion_date, completion_date_raw,
            completion_date_type, last_update_posted, last_update_posted_raw,
            lead_sponsor_name, lead_sponsor_class, collaborators, conditions,
            keywords, interventions, primary_outcomes, secondary_outcomes,
            locations, has_results, source, source_url, raw_sha256, raw_payload,
            schema_version
        ) VALUES (
            :nct_id, :brief_title, :official_title, :acronym, :overall_status,
            :why_stopped, :study_type, CAST(:phases AS JSONB), :enrollment,
            :enrollment_type, :start_date, :start_date_raw, :start_date_type,
            :primary_completion_date, :primary_completion_date_raw,
            :primary_completion_date_type, :completion_date, :completion_date_raw,
            :completion_date_type, :last_update_posted, :last_update_posted_raw,
            :lead_sponsor_name, :lead_sponsor_class,
            CAST(:collaborators AS JSONB), CAST(:conditions AS JSONB),
            CAST(:keywords AS JSONB), CAST(:interventions AS JSONB),
            CAST(:primary_outcomes AS JSONB), CAST(:secondary_outcomes AS JSONB),
            CAST(:locations AS JSONB), :has_results, :source, :source_url,
            :raw_sha256, CAST(:raw_payload AS JSONB), :schema_version
        ) ON CONFLICT (nct_id) DO UPDATE SET
            brief_title = EXCLUDED.brief_title,
            official_title = EXCLUDED.official_title,
            acronym = EXCLUDED.acronym,
            overall_status = EXCLUDED.overall_status,
            why_stopped = EXCLUDED.why_stopped,
            study_type = EXCLUDED.study_type,
            phases = EXCLUDED.phases,
            enrollment = EXCLUDED.enrollment,
            enrollment_type = EXCLUDED.enrollment_type,
            start_date = EXCLUDED.start_date,
            start_date_raw = EXCLUDED.start_date_raw,
            start_date_type = EXCLUDED.start_date_type,
            primary_completion_date = EXCLUDED.primary_completion_date,
            primary_completion_date_raw = EXCLUDED.primary_completion_date_raw,
            primary_completion_date_type = EXCLUDED.primary_completion_date_type,
            completion_date = EXCLUDED.completion_date,
            completion_date_raw = EXCLUDED.completion_date_raw,
            completion_date_type = EXCLUDED.completion_date_type,
            last_update_posted = EXCLUDED.last_update_posted,
            last_update_posted_raw = EXCLUDED.last_update_posted_raw,
            lead_sponsor_name = EXCLUDED.lead_sponsor_name,
            lead_sponsor_class = EXCLUDED.lead_sponsor_class,
            collaborators = EXCLUDED.collaborators,
            conditions = EXCLUDED.conditions,
            keywords = EXCLUDED.keywords,
            interventions = EXCLUDED.interventions,
            primary_outcomes = EXCLUDED.primary_outcomes,
            secondary_outcomes = EXCLUDED.secondary_outcomes,
            locations = EXCLUDED.locations,
            has_results = EXCLUDED.has_results,
            source = EXCLUDED.source,
            source_url = EXCLUDED.source_url,
            raw_sha256 = EXCLUDED.raw_sha256,
            raw_payload = EXCLUDED.raw_payload,
            schema_version = EXCLUDED.schema_version,
            last_seen_at = NOW()
    """), params)
    session.execute(text("""
        INSERT INTO clinical_trial_response_history (
            nct_id, response_sha256, raw_payload
        ) VALUES (
            :nct_id, :raw_sha256, CAST(:raw_payload AS JSONB)
        ) ON CONFLICT (nct_id, response_sha256) DO UPDATE SET
            last_fetched_at = NOW()
    """), params)
    session.execute(text("""
        INSERT INTO clinical_trial_status_history (
            nct_id, overall_status, why_stopped, source_last_update
        ) VALUES (
            :nct_id, :overall_status, :why_stopped, :last_update_posted
        ) ON CONFLICT DO NOTHING
    """), params)
    relationships = (
        0
        if existing is not None and existing["raw_sha256"] == raw_sha256
        else _link_study_entities(session, fields)
    )
    return {
        "created": int(existing is None),
        "updated": int(existing is not None and existing["raw_sha256"] != raw_sha256),
        "unchanged": int(existing is not None and existing["raw_sha256"] == raw_sha256),
        "status_changes": int(
            existing is not None and existing["overall_status"] != fields["overall_status"]
        ),
        "relationships": relationships,
    }


def _initial_window(
    session,
    *,
    lane: str,
    dataset_date: date,
    dataset_timestamp: datetime,
) -> dict[str, Any]:
    existing = session.execute(text("""
        SELECT * FROM clinical_trials_sync_state WHERE lane = :lane
    """), {"lane": lane}).mappings().first()
    existing_timestamp = existing.get("dataset_timestamp") if existing else None
    if existing_timestamp is not None and existing_timestamp.tzinfo is None:
        existing_timestamp = existing_timestamp.replace(tzinfo=timezone.utc)
    stale_page_token = bool(
        existing
        and existing.get("next_page_token")
        and existing_timestamp != dataset_timestamp
    )
    if lane == "recent":
        desired_start = dataset_date - timedelta(
            days=max(1, settings.clinicaltrials_recent_overlap_days)
        )
        if (
            existing
            and existing["status"] in {"running", "partial"}
            and existing["next_page_token"]
            and not stale_page_token
        ):
            # Tokens are valid only for the dataset snapshot that issued them.
            return dict(existing)
        return {
            "lane": lane,
            "window_start": desired_start,
            "window_end": dataset_date,
            "next_page_token": None,
        }

    if existing and existing["window_end"]:
        if stale_page_token:
            state = dict(existing)
            state["next_page_token"] = None
            return state
        if existing["status"] == "completed" and existing["window_end"] < dataset_date:
            start = existing["window_end"] + timedelta(days=1)
            return {
                "lane": lane,
                "window_start": start,
                "window_end": min(
                    dataset_date,
                    start + timedelta(days=settings.clinicaltrials_backfill_window_days - 1),
                ),
                "next_page_token": None,
            }
        return dict(existing)
    return {
        "lane": lane,
        "window_start": BACKFILL_START_DATE,
        "window_end": min(
            dataset_date,
            BACKFILL_START_DATE
            + timedelta(days=settings.clinicaltrials_backfill_window_days - 1),
        ),
        "next_page_token": None,
    }


def sync_clinical_trials(
    lane: str,
    *,
    client: ClinicalTrialsClient | None = None,
    page_size: int | None = None,
    max_pages: int | None = None,
) -> dict[str, Any]:
    """Advance a recent or historical API-v2 lane from durable state."""
    if lane not in {"recent", "backfill"}:
        raise ValueError("ClinicalTrials.gov lane must be recent or backfill")
    ensure_clinical_trials_schema()
    lock_connection = get_cortellis_engine().connect()
    acquired = bool(lock_connection.execute(text(
        "SELECT pg_try_advisory_lock(hashtext('onebd_clinical_trials_sync'))"
    )).scalar())
    if not acquired:
        lock_connection.close()
        return {
            "status": "skipped",
            "reason": "ClinicalTrials.gov sync already running",
            "lane": lane,
        }

    try:
        client = client or ClinicalTrialsClient()
        version = client.dataset_version()
        dataset_timestamp = _dataset_timestamp(version["dataTimestamp"])
        dataset_date = dataset_timestamp.date()
        page_size = page_size or settings.clinicaltrials_page_size
        max_pages = max_pages or (
            settings.clinicaltrials_recent_max_pages
            if lane == "recent" else settings.clinicaltrials_backfill_max_pages
        )
        totals = {
            "pages": 0,
            "studies_seen": 0,
            "studies_created": 0,
            "studies_updated": 0,
            "studies_unchanged": 0,
            "status_changes": 0,
            "relationships_created": 0,
        }

        with get_cortellis_session() as session:
            state = _initial_window(
                session,
                lane=lane,
                dataset_date=dataset_date,
                dataset_timestamp=dataset_timestamp,
            )
            if (
                lane == "backfill"
                and state.get("status") == "completed"
                and state.get("window_end") >= dataset_date
                and not state.get("next_page_token")
            ):
                return {
                    "status": "completed",
                    "lane": lane,
                    "pages": 0,
                    "studies_seen": 0,
                    "studies_created": 0,
                    "studies_updated": 0,
                    "studies_unchanged": 0,
                    "status_changes": 0,
                    "relationships_created": 0,
                    "cursor": dataset_date.isoformat(),
                    "source_data_at": dataset_timestamp.isoformat(),
                    "dataset_timestamp": dataset_timestamp.isoformat(),
                    "api_version": version.get("apiVersion"),
                    "window_start": state["window_start"].isoformat(),
                    "window_end": state["window_end"].isoformat(),
                    "has_more_pages": False,
                    "coverage_complete": True,
                }
            session.execute(text("""
                INSERT INTO clinical_trials_sync_state (
                    lane, window_start, window_end, next_page_token,
                    dataset_timestamp, status, last_started_at, updated_at
                ) VALUES (
                    :lane, :window_start, :window_end, :next_page_token,
                    :dataset_timestamp, 'running', NOW(), NOW()
                ) ON CONFLICT (lane) DO UPDATE SET
                    window_start = EXCLUDED.window_start,
                    window_end = EXCLUDED.window_end,
                    next_page_token = EXCLUDED.next_page_token,
                    dataset_timestamp = EXCLUDED.dataset_timestamp,
                    status = 'running',
                    last_error = NULL,
                    last_started_at = NOW(),
                    updated_at = NOW()
            """), {**state, "dataset_timestamp": dataset_timestamp})

        page_token = state.get("next_page_token")
        window_start = state["window_start"]
        window_end = state["window_end"]
        completed_to_dataset = False
        token_resets = 0
        while totals["pages"] < max_pages:
            page, token_was_reset = _updated_studies_page_with_token_recovery(
                client,
                start_date=window_start,
                end_date=window_end,
                page_size=page_size,
                page_token=page_token,
            )
            if token_was_reset:
                # Restart the idempotent window now instead of leaving the lane
                # failed until the next weekday.
                token_resets += 1
                page_token = None
                with get_cortellis_session() as session:
                    session.execute(text("""
                        UPDATE clinical_trials_sync_state
                        SET next_page_token = NULL,
                            updated_at = NOW()
                        WHERE lane = :lane
                    """), {"lane": lane})
            with get_cortellis_session() as session:
                for study in page.studies:
                    outcome = _upsert_study(session, study)
                    totals["studies_seen"] += 1
                    totals["studies_created"] += outcome["created"]
                    totals["studies_updated"] += outcome["updated"]
                    totals["studies_unchanged"] += outcome["unchanged"]
                    totals["status_changes"] += outcome["status_changes"]
                    totals["relationships_created"] += outcome["relationships"]
                totals["pages"] += 1
                page_token = page.next_page_token
                session.execute(text("""
                    UPDATE clinical_trials_sync_state
                    SET next_page_token = :page_token,
                        pages_processed = pages_processed + 1,
                        studies_processed = studies_processed + :studies,
                        updated_at = NOW()
                    WHERE lane = :lane
                """), {
                    "page_token": page_token,
                    "studies": len(page.studies),
                    "lane": lane,
                })

            if page_token:
                continue
            if lane == "recent" or window_end >= dataset_date:
                completed_to_dataset = True
                break
            window_start = window_end + timedelta(days=1)
            window_end = min(
                dataset_date,
                window_start
                + timedelta(days=settings.clinicaltrials_backfill_window_days - 1),
            )
            with get_cortellis_session() as session:
                session.execute(text("""
                    UPDATE clinical_trials_sync_state
                    SET window_start = :window_start,
                        window_end = :window_end,
                        next_page_token = NULL,
                        updated_at = NOW()
                    WHERE lane = :lane
                """), {
                    "window_start": window_start,
                    "window_end": window_end,
                    "lane": lane,
                })

        checkpoint_status = "completed" if completed_to_dataset else "partial"
        with get_cortellis_session() as session:
            session.execute(text("""
                UPDATE clinical_trials_sync_state
                SET status = :status,
                    last_error = :error,
                    last_completed_at = NOW(),
                    updated_at = NOW()
                WHERE lane = :lane
            """), {
                "status": checkpoint_status,
                "error": (
                    None if completed_to_dataset else "Per-run page budget reached"
                ),
                "lane": lane,
            })

        return {
            # A bounded batch that durably advances its cursor is a healthy run.
            # Full-registry coverage is reported independently below.
            "status": "completed",
            "checkpoint_status": checkpoint_status,
            "lane": lane,
            **totals,
            "cursor": window_end.isoformat(),
            "source_data_at": dataset_timestamp.isoformat(),
            "dataset_timestamp": dataset_timestamp.isoformat(),
            "api_version": version.get("apiVersion"),
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "has_more_pages": not completed_to_dataset,
            "coverage_complete": completed_to_dataset,
            "page_token_resets": token_resets,
        }
    except Exception as exc:
        try:
            with get_cortellis_session() as session:
                session.execute(text("""
                    UPDATE clinical_trials_sync_state
                    SET status = 'failed',
                        last_error = :error,
                        last_completed_at = NOW(),
                        updated_at = NOW()
                    WHERE lane = :lane
                """), {"error": str(exc)[:4000], "lane": lane})
        except Exception:
            # Preserve the source exception; the common monitor records it too.
            pass
        raise
    finally:
        try:
            lock_connection.execute(text(
                "SELECT pg_advisory_unlock(hashtext('onebd_clinical_trials_sync'))"
            ))
        finally:
            lock_connection.close()


def clinical_trials_status() -> dict[str, Any]:
    """Return source inventory, link coverage, and both durable cursors."""
    ensure_clinical_trials_schema()
    with get_cortellis_session() as session:
        inventory = dict(session.execute(text("""
            SELECT
                COUNT(*) AS trials,
                COUNT(*) FILTER (WHERE has_results) AS trials_with_results,
                COUNT(*) FILTER (
                    WHERE overall_status IN (
                        'RECRUITING', 'NOT_YET_RECRUITING',
                        'ACTIVE_NOT_RECRUITING', 'ENROLLING_BY_INVITATION'
                    )
                ) AS active_trials,
                COUNT(DISTINCT nct_id) FILTER (
                    WHERE EXISTS (
                        SELECT 1 FROM clinical_trial_drugs link
                        WHERE link.nct_id = clinical_trials.nct_id
                    )
                ) AS trials_linked_to_drugs,
                COUNT(DISTINCT nct_id) FILTER (
                    WHERE EXISTS (
                        SELECT 1 FROM clinical_trial_companies link
                        WHERE link.nct_id = clinical_trials.nct_id
                    )
                ) AS trials_linked_to_companies,
                MAX(last_update_posted) AS latest_source_update
            FROM clinical_trials
        """)).mappings().one())
        lanes = [dict(row) for row in session.execute(text("""
            SELECT lane, window_start, window_end, next_page_token IS NOT NULL
                       AS has_page_token,
                   dataset_timestamp, status, pages_processed,
                   studies_processed, last_error, last_started_at,
                   last_completed_at, updated_at
            FROM clinical_trials_sync_state
            ORDER BY lane
        """)).mappings().all()]
    return {**inventory, "lanes": lanes, "source": CLINICALTRIALS_SOURCE}
