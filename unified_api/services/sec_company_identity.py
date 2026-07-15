"""Authoritative SEC company-identity audit and identifier enrichment."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from typing import Any

from sqlalchemy import text

from unified_api.config import settings
from unified_api.services.database import (
    get_cortellis_engine,
    get_cortellis_session,
    get_edgar_session,
)
from unified_api.services.entity_resolution import (
    EntityResolutionService,
    get_entity_resolution_service,
    normalize_identifier_value,
)
from unified_api.services.public_source_http import (
    PublicSourceHttpClient,
    RetryPolicy,
)


SEC_SUBMISSIONS_SOURCE = "sec_company_submissions"
_identity_schema_ready = False
_lei_pattern = re.compile(r"[A-Z0-9]{20}\Z")


class SecCompanySubmissionsClient:
    """Rate-limited adapter for official SEC submissions identity records."""

    def __init__(self, *, base_url: str = "https://data.sec.gov"):
        self._http = PublicSourceHttpClient(
            source=SEC_SUBMISSIONS_SOURCE,
            base_url=base_url,
            user_agent=settings.edgar_user_agent,
            timeout=30,
            min_interval_seconds=0.12,
            retry_policy=RetryPolicy(max_retries=3),
        )

    def company(self, cik: str):
        normalized = _normalize_cik(cik)
        response = self._http.get_json(f"/submissions/CIK{normalized}.json")
        if response is None:
            raise RuntimeError(f"SEC returned no submissions record for CIK {normalized}")
        return response


def _normalize_cik(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if not digits or len(digits) > 10:
        raise ValueError(f"Invalid SEC CIK: {value}")
    return digits.zfill(10)


def _normalized_company_name(value: str) -> str:
    return EntityResolutionService().normalize_company_name(value)


def sec_identity_name_match(
    source_name: str,
    candidate_names: list[str],
) -> tuple[bool, str | None]:
    """Accept only a normalized-exact SEC name or retained company alias."""
    source = _normalized_company_name(source_name)
    for candidate in candidate_names:
        if source and source == _normalized_company_name(candidate):
            return True, candidate
    return False, None


def sec_submission_identifiers(payload: dict[str, Any]) -> list[dict[str, str]]:
    """Extract only validated LEI and hostname values explicitly reported to SEC."""
    identifiers: list[dict[str, str]] = []
    lei = normalize_identifier_value("lei", str(payload.get("lei") or ""))
    if lei:
        if not _lei_pattern.fullmatch(lei):
            raise ValueError(f"SEC submissions record contained an invalid LEI: {lei}")
        identifiers.append({
            "identifier_type": "lei",
            "identifier_value": lei,
            "normalized_value": lei,
            "source_field": "lei",
        })
    seen_domains: set[str] = set()
    for source_field in ("website", "investorWebsite"):
        raw_value = str(payload.get(source_field) or "").strip()
        if not raw_value:
            continue
        domain = normalize_identifier_value("domain", raw_value)
        if not domain or "." not in domain or " " in domain:
            raise ValueError(
                f"SEC submissions record contained an invalid domain: {raw_value}"
            )
        if domain in seen_domains:
            continue
        seen_domains.add(domain)
        identifiers.append({
            "identifier_type": "domain",
            "identifier_value": raw_value,
            "normalized_value": domain,
            "source_field": source_field,
        })
    return identifiers


def validate_roche_wtw_repair_sources(
    willis_payload: dict[str, Any],
    roche_payload: dict[str, Any],
) -> None:
    """Refuse the known repair unless both live SEC identities are exact."""
    expected = (
        (willis_payload, "0001140536", "WILLIS TOWERS WATSON PLC"),
        (roche_payload, "0000889131", "ROCHE HOLDING LTD"),
    )
    for payload, cik, name in expected:
        if _normalize_cik(payload.get("cik")) != cik:
            raise ValueError(f"SEC repair source did not return expected CIK {cik}")
        matched, _ = sec_identity_name_match(str(payload.get("name") or ""), [name])
        if not matched:
            raise ValueError(
                f"SEC CIK {cik} did not return expected legal name {name}"
            )


def repair_roche_wtw_misattribution(
    *,
    client: SecCompanySubmissionsClient | None = None,
) -> dict[str, Any]:
    """Repair the historical hard-coded Roche/WTW CIK misattribution.

    The operation is deliberately narrow and idempotent. It first revalidates
    both CIKs against live official SEC submissions records, restores the
    existing 83-document Edgar company to its real WTW identity, creates or
    reuses the correct Roche Edgar entity, and then repoints the Cortellis xref.
    """
    ensure_sec_company_identity_schema()
    source_client = client or SecCompanySubmissionsClient()
    willis_response = source_client.company("0001140536")
    roche_response = source_client.company("0000889131")
    validate_roche_wtw_repair_sources(
        willis_response.payload,
        roche_response.payload,
    )

    with get_edgar_session() as session:
        willis = session.execute(text("""
            SELECT id, name, ticker, country
            FROM companies WHERE cik = '0001140536'
        """)).mappings().first()
        if not willis:
            raise RuntimeError("Edgar company for CIK 0001140536 was not found")
        current_normalized = _normalized_company_name(str(willis["name"]))
        allowed_names = {
            _normalized_company_name("Roche Holding Ltd"),
            _normalized_company_name("Willis Towers Watson plc"),
        }
        if current_normalized not in allowed_names:
            raise RuntimeError(
                "Refusing to rewrite unexpected Edgar company name "
                f"{willis['name']} for CIK 0001140536"
            )
        session.execute(text("""
            UPDATE companies
            SET name = 'WILLIS TOWERS WATSON PLC',
                ticker = 'WTW',
                country = 'Ireland',
                sector = 'Insurance Agents, Brokers & Service',
                aliases = '[]'::JSONB
            WHERE id = :company_id
        """), {"company_id": willis["id"]})

        roche = session.execute(text("""
            SELECT id, name FROM companies WHERE cik = '0000889131'
        """)).mappings().first()
        if roche:
            if _normalized_company_name(str(roche["name"])) != (
                _normalized_company_name("Roche Holding Ltd")
            ):
                raise RuntimeError(
                    "Correct Roche CIK is already assigned to unexpected Edgar "
                    f"company {roche['name']}"
                )
            roche_edgar_id = int(roche["id"])
            session.execute(text("""
                UPDATE companies
                SET ticker = COALESCE(ticker, 'RHHBY'),
                    country = COALESCE(country, 'Switzerland'),
                    sector = COALESCE(sector, 'Pharmaceuticals')
                WHERE id = :company_id
            """), {"company_id": roche_edgar_id})
        else:
            roche_edgar_id = int(session.execute(text("""
                INSERT INTO companies (
                    cik, ticker, name, country, sector, aliases
                ) VALUES (
                    '0000889131', 'RHHBY', 'ROCHE HOLDING LTD',
                    'Switzerland', 'Pharmaceuticals', '[]'::JSONB
                ) RETURNING id
            """)).scalar_one())

    with get_cortellis_session() as session:
        company = session.execute(text("""
            SELECT id, name FROM companies WHERE id = 19446
        """)).mappings().first()
        if not company or _normalized_company_name(str(company["name"])) != (
            _normalized_company_name("Roche Holding Ltd")
        ):
            raise RuntimeError("Cortellis company 19446 is not Roche Holding Ltd")
        conflict = session.execute(text("""
            SELECT cortellis_id FROM company_xref
            WHERE cik = '0000889131' AND cortellis_id <> 19446
        """)).scalar()
        if conflict is not None:
            raise RuntimeError(
                f"Correct Roche CIK is already mapped to Cortellis company {conflict}"
            )
        session.execute(text("""
            UPDATE companies
            SET cik = '0000889131', ticker = COALESCE(ticker, 'RHHBY')
            WHERE id = 19446
        """))
        xref_update = session.execute(text("""
            UPDATE company_xref
            SET cik = '0000889131',
                ticker = COALESCE(ticker, 'RHHBY'),
                canonical_name = 'ROCHE HOLDING LTD',
                edgar_company_id = :edgar_company_id,
                match_method = 'sec_cik_name_verified',
                match_confidence = 1.0,
                manually_verified = TRUE,
                verified_by = 'official SEC submissions repair',
                verified_at = NOW(),
                updated_at = NOW()
            WHERE cortellis_id = 19446
        """), {"edgar_company_id": roche_edgar_id})
        if xref_update.rowcount != 1:
            raise RuntimeError("Expected exactly one Roche company_xref row to repair")
        session.execute(text("""
            DELETE FROM company_identity_source_state
            WHERE source = :source AND company_id = 19446
        """), {"source": SEC_SUBMISSIONS_SOURCE})

    return {
        "status": "repaired",
        "willis": {
            "edgar_company_id": int(willis["id"]),
            "cik": "0001140536",
            "name": "WILLIS TOWERS WATSON PLC",
        },
        "roche": {
            "cortellis_company_id": 19446,
            "edgar_company_id": roche_edgar_id,
            "cik": "0000889131",
            "name": "ROCHE HOLDING LTD",
        },
        "source": SEC_SUBMISSIONS_SOURCE,
    }


def _identity_schema_is_current() -> bool:
    """Check required identity columns without taking table-level DDL locks."""
    required = {
        ("company_aliases", "evidence"),
        ("company_aliases", "review_status"),
        ("company_aliases", "source_reference"),
        ("company_identifiers", "normalized_value"),
        ("company_identifiers", "review_status"),
        ("company_identity_relationships", "evidence"),
        ("company_identity_relationships", "review_status"),
        ("company_identity_source_responses", "raw_response"),
        ("company_identity_source_responses", "response_sha256"),
        ("company_identity_source_state", "next_retry_at"),
        ("company_identity_source_state", "response_sha256"),
    }
    with get_cortellis_engine().connect() as connection:
        rows = connection.execute(text("""
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name IN (
                  'company_aliases',
                  'company_identifiers',
                  'company_identity_relationships',
                  'company_identity_source_responses',
                  'company_identity_source_state'
              )
        """)).all()
    return required.issubset({(str(row[0]), str(row[1])) for row in rows})


def ensure_sec_company_identity_schema() -> None:
    """Create durable SEC identity source-response and scan-state tables."""
    global _identity_schema_ready
    if _identity_schema_ready:
        return
    from unified_api.services.runtime_schema import runtime_schema_is_pre_migrated

    if runtime_schema_is_pre_migrated():
        _identity_schema_ready = True
        return
    if _identity_schema_is_current():
        _identity_schema_ready = True
        return

    # Only the rare migration path takes DDL locks. Recheck after acquiring a
    # global schema lock so multiple freshly started workers cannot race here.
    lock = get_cortellis_engine().connect()
    lock.execute(text(
        "SELECT pg_advisory_lock(hashtext('onebd_company_identity_schema'))"
    ))
    try:
        if _identity_schema_is_current():
            _identity_schema_ready = True
            return
        get_entity_resolution_service().ensure_identity_schema()
        with get_cortellis_session() as session:
            session.execute(text("""
                CREATE TABLE IF NOT EXISTS company_identity_source_responses (
                    id BIGSERIAL PRIMARY KEY,
                    company_id INTEGER NOT NULL REFERENCES companies(id)
                        ON DELETE CASCADE,
                    source VARCHAR(100) NOT NULL,
                    source_key VARCHAR(100) NOT NULL,
                    request_url TEXT NOT NULL,
                    fetched_at TIMESTAMPTZ NOT NULL,
                    source_date TEXT,
                    response_sha256 CHAR(64) NOT NULL,
                    raw_response JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (source, source_key, response_sha256)
                )
            """))
            session.execute(text("""
                CREATE INDEX IF NOT EXISTS ix_company_identity_responses_company
                ON company_identity_source_responses (company_id, source, fetched_at)
            """))
            session.execute(text("""
                CREATE TABLE IF NOT EXISTS company_identity_source_state (
                    source VARCHAR(100) NOT NULL,
                    company_id INTEGER NOT NULL REFERENCES companies(id)
                        ON DELETE CASCADE,
                    source_key VARCHAR(100) NOT NULL,
                    status VARCHAR(30) NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    source_name TEXT,
                    normalized_source_name TEXT,
                    matched_name TEXT,
                    identifiers_written INTEGER NOT NULL DEFAULT 0,
                    response_sha256 CHAR(64),
                    last_error TEXT,
                    last_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    next_retry_at TIMESTAMPTZ,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (source, company_id)
                )
            """))
            session.execute(text("""
                CREATE INDEX IF NOT EXISTS ix_company_identity_state_queue
                ON company_identity_source_state (
                    source, status, next_retry_at, company_id
                )
            """))
        _identity_schema_ready = True
    finally:
        try:
            lock.execute(text(
                "SELECT pg_advisory_unlock(hashtext('onebd_company_identity_schema'))"
            ))
        finally:
            lock.close()


def _sec_candidates(batch_size: int, *, refresh: bool) -> list[dict[str, Any]]:
    with get_cortellis_session() as session:
        rows = session.execute(text("""
            SELECT company.id AS company_id,
                   company.name AS company_name,
                   xref.id AS xref_id,
                   xref.cik,
                   xref.canonical_name,
                   ARRAY(
                       SELECT alias.alias_value
                       FROM company_aliases alias
                       WHERE alias.xref_id = xref.id
                       ORDER BY alias.id
                   ) AS aliases
            FROM company_xref xref
            JOIN companies company ON company.id = xref.cortellis_id
            LEFT JOIN company_identity_source_state state
              ON state.source = :source
             AND state.company_id = company.id
            WHERE xref.cik IS NOT NULL
              AND xref.cik <> ''
              AND (
                  :refresh
                  OR state.company_id IS NULL
                  OR (
                      state.status = 'failed'
                      AND COALESCE(state.next_retry_at, NOW()) <= NOW()
                  )
              )
            ORDER BY company.id
            LIMIT :limit
        """), {
            "source": SEC_SUBMISSIONS_SOURCE,
            "refresh": refresh,
            "limit": batch_size,
        }).mappings().all()
    return [dict(row) for row in rows]


def _archive_response(session, candidate: dict[str, Any], response) -> str:
    raw_json = json.dumps(response.payload, sort_keys=True, separators=(",", ":"))
    response_sha = hashlib.sha256(raw_json.encode()).hexdigest()
    session.execute(text("""
        INSERT INTO company_identity_source_responses (
            company_id, source, source_key, request_url, fetched_at,
            source_date, response_sha256, raw_response
        ) VALUES (
            :company_id, :source, :source_key, :request_url, :fetched_at,
            :source_date, :response_sha, CAST(:raw_response AS JSONB)
        ) ON CONFLICT (source, source_key, response_sha256)
          DO UPDATE SET fetched_at = EXCLUDED.fetched_at
    """), {
        "company_id": candidate["company_id"],
        "source": SEC_SUBMISSIONS_SOURCE,
        "source_key": candidate["cik"],
        "request_url": response.request_url,
        "fetched_at": response.fetched_at,
        "source_date": response.source_date,
        "response_sha": response_sha,
        "raw_response": raw_json,
    })
    return response_sha


def _record_state(
    session,
    candidate: dict[str, Any],
    *,
    status: str,
    source_name: str | None = None,
    matched_name: str | None = None,
    identifiers_written: int = 0,
    response_sha: str | None = None,
    error: str | None = None,
) -> None:
    next_retry_at = None
    if status == "failed":
        next_retry_at = datetime.now(timezone.utc) + timedelta(hours=6)
    session.execute(text("""
        INSERT INTO company_identity_source_state (
            source, company_id, source_key, status, attempts, source_name,
            normalized_source_name, matched_name, identifiers_written,
            response_sha256, last_error, last_attempt_at, next_retry_at, updated_at
        ) VALUES (
            :source, :company_id, :source_key, :status, 1, :source_name,
            :normalized_source_name, :matched_name, :identifiers_written,
            :response_sha, :error, NOW(), :next_retry_at, NOW()
        ) ON CONFLICT (source, company_id) DO UPDATE SET
            source_key = EXCLUDED.source_key,
            status = EXCLUDED.status,
            attempts = company_identity_source_state.attempts + 1,
            source_name = EXCLUDED.source_name,
            normalized_source_name = EXCLUDED.normalized_source_name,
            matched_name = EXCLUDED.matched_name,
            identifiers_written = EXCLUDED.identifiers_written,
            response_sha256 = EXCLUDED.response_sha256,
            last_error = EXCLUDED.last_error,
            last_attempt_at = NOW(),
            next_retry_at = EXCLUDED.next_retry_at,
            updated_at = NOW()
    """), {
        "source": SEC_SUBMISSIONS_SOURCE,
        "company_id": candidate["company_id"],
        "source_key": candidate["cik"],
        "status": status,
        "source_name": source_name,
        "normalized_source_name": (
            _normalized_company_name(source_name) if source_name else None
        ),
        "matched_name": matched_name,
        "identifiers_written": identifiers_written,
        "response_sha": response_sha,
        "error": error,
        "next_retry_at": next_retry_at,
    })


def _upsert_identifiers(
    session,
    candidate: dict[str, Any],
    identifiers: list[dict[str, str]],
    *,
    response_sha: str,
    request_url: str,
    source_name: str,
) -> int:
    written = 0
    for identifier in identifiers:
        evidence = json.dumps({
            "cik": candidate["cik"],
            "cortellis_name": candidate["company_name"],
            "sec_name": source_name,
            "source_field": identifier["source_field"],
            "response_sha256": response_sha,
        }, sort_keys=True)
        result = session.execute(text("""
            INSERT INTO company_identifiers (
                company_id, identifier_type, identifier_value,
                normalized_value, source, source_reference, evidence,
                confidence, review_status, reviewed_by, reviewed_at
            ) VALUES (
                :company_id, :identifier_type, :identifier_value,
                :normalized_value, :source, :source_reference,
                CAST(:evidence AS JSONB), 1.0, 'verified',
                'SEC submissions exact CIK/name audit', NOW()
            ) ON CONFLICT (identifier_type, normalized_value) DO UPDATE SET
                identifier_value = EXCLUDED.identifier_value,
                source = EXCLUDED.source,
                source_reference = EXCLUDED.source_reference,
                evidence = EXCLUDED.evidence,
                confidence = EXCLUDED.confidence,
                review_status = EXCLUDED.review_status,
                reviewed_by = EXCLUDED.reviewed_by,
                reviewed_at = EXCLUDED.reviewed_at,
                updated_at = NOW()
            WHERE company_identifiers.company_id = EXCLUDED.company_id
            RETURNING id
        """), {
            "company_id": candidate["company_id"],
            "identifier_type": identifier["identifier_type"],
            "identifier_value": identifier["identifier_value"],
            "normalized_value": identifier["normalized_value"],
            "source": SEC_SUBMISSIONS_SOURCE,
            "source_reference": request_url,
            "evidence": evidence,
        }).first()
        if result:
            written += 1
    return written


def _upsert_former_names(
    session,
    candidate: dict[str, Any],
    payload: dict[str, Any],
    *,
    request_url: str,
    response_sha: str,
) -> None:
    for former in payload.get("formerNames") or []:
        alias_value = str(former.get("name") or "").strip()
        if not alias_value:
            continue
        normalized = re.sub(r"[^a-z0-9]+", "", alias_value.casefold())
        session.execute(text("""
            INSERT INTO company_aliases (
                xref_id, alias_type, alias_value, effective_from, effective_to,
                source, normalized_value, source_reference, evidence,
                confidence, review_status, reviewed_by, reviewed_at
            ) VALUES (
                :xref_id, 'former_legal_name', :alias_value,
                CAST(:effective_from AS DATE), CAST(:effective_to AS DATE),
                :source, :normalized, :source_reference,
                CAST(:evidence AS JSONB), 1.0, 'verified',
                'SEC submissions exact CIK/name audit', NOW()
            ) ON CONFLICT DO NOTHING
        """), {
            "xref_id": candidate["xref_id"],
            "alias_value": alias_value,
            "effective_from": former.get("from"),
            "effective_to": former.get("to"),
            "source": SEC_SUBMISSIONS_SOURCE,
            "normalized": normalized,
            "source_reference": request_url,
            "evidence": json.dumps({
                "cik": candidate["cik"],
                "response_sha256": response_sha,
            }, sort_keys=True),
        })


def audit_sec_company_identities(
    *,
    batch_size: int = 100,
    refresh: bool = False,
    client: SecCompanySubmissionsClient | None = None,
) -> dict[str, Any]:
    """Audit CIK ownership before retaining SEC-reported identity fields."""
    ensure_sec_company_identity_schema()
    lock = get_cortellis_engine().connect()
    acquired = bool(lock.execute(text(
        "SELECT pg_try_advisory_lock(hashtext('onebd_sec_company_identity'))"
    )).scalar())
    if not acquired:
        lock.close()
        return {"status": "skipped", "reason": "SEC company identity audit running"}
    try:
        candidates = _sec_candidates(batch_size, refresh=refresh)
        if not candidates:
            return {
                "status": "completed",
                "processed": 0,
                "matched": 0,
                "name_mismatches": 0,
                "identifiers_written": 0,
                "failed": 0,
            }
        source_client = client or SecCompanySubmissionsClient()
        totals = {
            "processed": 0,
            "matched": 0,
            "name_mismatches": 0,
            "identifiers_written": 0,
            "failed": 0,
        }
        with get_cortellis_session() as session:
            for candidate in candidates:
                totals["processed"] += 1
                try:
                    # Keep one bad row from aborting the remaining batch and
                    # preventing its durable failure state from being written.
                    outcome = "matched"
                    written = 0
                    with session.begin_nested():
                        response = source_client.company(candidate["cik"])
                        response_sha = _archive_response(session, candidate, response)
                        payload = response.payload
                        source_cik = _normalize_cik(payload.get("cik"))
                        if source_cik != _normalize_cik(candidate["cik"]):
                            raise ValueError(
                                f"SEC response CIK {source_cik} did not match request"
                            )
                        source_name = str(payload.get("name") or "").strip()
                        candidate_names = [
                            candidate["company_name"],
                            candidate["canonical_name"],
                            *(candidate.get("aliases") or []),
                        ]
                        matched, matched_name = sec_identity_name_match(
                            source_name,
                            candidate_names,
                        )
                        if not matched:
                            outcome = "name_mismatch"
                            _record_state(
                                session,
                                candidate,
                                status="name_mismatch",
                                source_name=source_name,
                                response_sha=response_sha,
                                error=(
                                    f"SEC CIK belongs to {source_name}; expected "
                                    f"one of {candidate_names}"
                                ),
                            )
                        else:
                            identifiers = sec_submission_identifiers(payload)
                            written = _upsert_identifiers(
                                session,
                                candidate,
                                identifiers,
                                response_sha=response_sha,
                                request_url=response.request_url,
                                source_name=source_name,
                            )
                            _upsert_former_names(
                                session,
                                candidate,
                                payload,
                                request_url=response.request_url,
                                response_sha=response_sha,
                            )
                            _record_state(
                                session,
                                candidate,
                                status="matched",
                                source_name=source_name,
                                matched_name=matched_name,
                                identifiers_written=written,
                                response_sha=response_sha,
                            )
                    if outcome == "name_mismatch":
                        totals["name_mismatches"] += 1
                    else:
                        totals["matched"] += 1
                        totals["identifiers_written"] += written
                except Exception as exc:  # noqa: BLE001 - durable per-record state
                    totals["failed"] += 1
                    with session.begin_nested():
                        _record_state(
                            session,
                            candidate,
                            status="failed",
                            error=str(exc)[:2000],
                        )
        return {
            "status": "partial" if totals["failed"] else "completed",
            **totals,
        }
    finally:
        try:
            lock.execute(text(
                "SELECT pg_advisory_unlock(hashtext('onebd_sec_company_identity'))"
            ))
        finally:
            lock.close()


def sec_company_identity_status() -> dict[str, Any]:
    """Return SEC audit coverage, mismatches, and retained identifiers."""
    ensure_sec_company_identity_schema()
    with get_cortellis_session() as session:
        summary = session.execute(text("""
            SELECT
              (SELECT COUNT(*) FROM company_xref
               WHERE cik IS NOT NULL AND cik <> '') AS eligible,
              COUNT(*) AS scanned,
              COUNT(*) FILTER (WHERE status = 'matched') AS matched,
              COUNT(*) FILTER (WHERE status = 'name_mismatch') AS name_mismatches,
              COUNT(*) FILTER (WHERE status = 'failed') AS failed,
              COALESCE(SUM(identifiers_written), 0) AS identifiers_written,
              MAX(last_attempt_at) AS last_attempt_at
            FROM company_identity_source_state
            WHERE source = :source
        """), {"source": SEC_SUBMISSIONS_SOURCE}).mappings().one()
        identifiers = session.execute(text("""
            SELECT identifier_type, review_status, COUNT(*) AS records
            FROM company_identifiers
            WHERE source = :source
            GROUP BY identifier_type, review_status
            ORDER BY identifier_type, review_status
        """), {"source": SEC_SUBMISSIONS_SOURCE}).mappings().all()
        mismatches = session.execute(text("""
            SELECT state.company_id, company.name AS cortellis_name,
                   xref.cik, state.source_name AS sec_name, state.last_error
            FROM company_identity_source_state state
            JOIN companies company ON company.id = state.company_id
            LEFT JOIN company_xref xref ON xref.cortellis_id = state.company_id
            WHERE state.source = :source
              AND state.status = 'name_mismatch'
            ORDER BY state.company_id
            LIMIT 100
        """), {"source": SEC_SUBMISSIONS_SOURCE}).mappings().all()
    result = dict(summary)
    result["coverage_pct"] = round(
        100 * int(summary["scanned"] or 0) / max(1, int(summary["eligible"] or 0)),
        2,
    )
    result["identifiers"] = [dict(row) for row in identifiers]
    result["mismatches"] = [dict(row) for row in mismatches]
    result["source"] = SEC_SUBMISSIONS_SOURCE
    return result
