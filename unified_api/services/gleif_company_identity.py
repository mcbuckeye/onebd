"""Conservative GLEIF LEI and Level 2 ownership enrichment."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import text

from unified_api.config import settings
from unified_api.services.database import (
    get_cortellis_engine,
    get_cortellis_session,
)
from unified_api.services.entity_resolution import (
    normalize_identifier_value,
)
from unified_api.services.public_source_http import (
    PublicSourceHttpClient,
    RetryPolicy,
)
from unified_api.services.sec_company_identity import (
    SEC_SUBMISSIONS_SOURCE,
    ensure_sec_company_identity_schema,
)


GLEIF_SEARCH_SOURCE = "gleif_lei_search"
GLEIF_RECORD_SOURCE = "gleif_lei_record"
GLEIF_STATE_SOURCE = "gleif_company_identity"
GLEIF_OWNERSHIP_SOURCE = "gleif_company_ownership"
GLEIF_RELATIONSHIP_SOURCE = "gleif_level_2"
GLEIF_PAGE_SIZE = 100

_lei_pattern = re.compile(r"[A-Z0-9]{20}\Z")


class GleifClient:
    """Rate-limited adapter for the official GLEIF JSON:API."""

    def __init__(self, *, base_url: str | None = None):
        self._base_url = (base_url or settings.gleif_base_url).rstrip("/")
        self._http = PublicSourceHttpClient(
            source=GLEIF_SEARCH_SOURCE,
            base_url=self._base_url,
            user_agent=settings.public_data_user_agent,
            timeout=30,
            min_interval_seconds=settings.gleif_request_interval_seconds,
            retry_policy=RetryPolicy(max_retries=3),
        )

    def search_legal_name(self, name: str):
        response = self._http.get_json(
            "/api/v1/lei-records",
            {
                "filter[entity.legalName]": name,
                "page[size]": GLEIF_PAGE_SIZE,
            },
        )
        if response is None:
            raise RuntimeError("GLEIF returned no legal-name search response")
        return response

    def record(self, lei: str):
        normalized = normalize_lei(lei)
        response = self._http.get_json(f"/api/v1/lei-records/{normalized}")
        if response is None:
            raise RuntimeError(f"GLEIF returned no LEI record for {normalized}")
        return response

    def related(self, url: str):
        parsed = urlsplit(url)
        base_host = urlsplit(self._base_url).hostname
        if parsed.scheme != "https" or parsed.hostname != base_host:
            raise ValueError(f"Refusing unexpected GLEIF relationship URL: {url}")
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        response = self._http.get_json(path)
        if response is None:
            raise RuntimeError(f"GLEIF returned no relationship response for {url}")
        return response


def normalize_lei(value: Any) -> str:
    """Return a validated ISO 17442 LEI."""
    normalized = normalize_identifier_value("lei", str(value or ""))
    if not _lei_pattern.fullmatch(normalized):
        raise ValueError(f"Invalid LEI: {value}")
    return normalized


def strict_legal_name(value: str) -> str:
    """Normalize punctuation and whitespace without discarding legal suffixes."""
    normalized = str(value or "").casefold().replace("&", " and ")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def gleif_record_names(record: dict[str, Any]) -> list[str]:
    """Return the legal and alternate names explicitly carried by GLEIF."""
    entity = (record.get("attributes") or {}).get("entity") or {}
    values = [((entity.get("legalName") or {}).get("name"))]
    for key in ("otherNames", "transliteratedOtherNames"):
        values.extend(item.get("name") for item in (entity.get(key) or []))
    return list(dict.fromkeys(str(value).strip() for value in values if value))


def _record_is_current(record: dict[str, Any]) -> bool:
    attributes = record.get("attributes") or {}
    entity = attributes.get("entity") or {}
    registration = attributes.get("registration") or {}
    return (
        entity.get("status") == "ACTIVE"
        and registration.get("status") in {"ISSUED", "LAPSED"}
    )


def select_unique_gleif_match(
    records: list[dict[str, Any]],
    candidate_names: list[str],
) -> tuple[str, dict[str, Any] | None, str | None]:
    """Choose one current exact-name LEI record or return a safe terminal state."""
    candidates = {
        strict_legal_name(name): name
        for name in candidate_names
        if strict_legal_name(name)
    }
    exact: dict[str, tuple[dict[str, Any], str]] = {}
    inactive = 0
    for record in records:
        try:
            lei = normalize_lei(record.get("id") or record.get("attributes", {}).get("lei"))
        except ValueError:
            continue
        matched_name = next(
            (
                source_name
                for source_name in gleif_record_names(record)
                if strict_legal_name(source_name) in candidates
            ),
            None,
        )
        if not matched_name:
            continue
        if not _record_is_current(record):
            inactive += 1
            continue
        exact[lei] = (record, matched_name)

    issued = {
        lei: match
        for lei, match in exact.items()
        if (match[0].get("attributes", {}).get("registration") or {}).get(
            "status"
        ) == "ISSUED"
    }
    selected = issued if issued else exact
    if len(selected) == 1:
        record, matched_name = next(iter(selected.values()))
        return "matched", record, matched_name
    if len(selected) > 1:
        return "ambiguous", None, None
    if inactive:
        return "inactive", None, None
    return "no_match", None, None


def _candidate_names(candidate: dict[str, Any]) -> list[str]:
    return list(dict.fromkeys(
        str(value).strip()
        for value in [
            candidate.get("company_name"),
            candidate.get("canonical_name"),
            *(candidate.get("aliases") or []),
        ]
        if value and strict_legal_name(str(value))
    ))


def _search_terms(candidate: dict[str, Any]) -> list[str]:
    """Prefer full Cortellis/legal names before broader canonical aliases."""
    return _candidate_names(candidate)[:6]


def _archive_response(
    session,
    *,
    company_id: int,
    source: str,
    source_key: str,
    response,
) -> str:
    raw_json = json.dumps(response.payload, sort_keys=True, separators=(",", ":"))
    response_sha = hashlib.sha256(raw_json.encode()).hexdigest()
    session.execute(text("""
        INSERT INTO company_identity_source_responses (
            company_id, source, source_key, request_url, fetched_at,
            source_date, response_sha256, raw_response
        ) VALUES (
            :company_id, :source, :source_key, :request_url, :fetched_at,
            :source_date, :response_sha, CAST(:raw_response AS JSONB)
        ) ON CONFLICT (source, source_key, response_sha256) DO NOTHING
    """), {
        "company_id": company_id,
        "source": source,
        "source_key": source_key,
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
    source: str,
    status: str,
    source_key: str,
    source_name: str | None = None,
    matched_name: str | None = None,
    written: int = 0,
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
            :normalized_source_name, :matched_name, :written,
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
        "source": source,
        "company_id": candidate["company_id"],
        "source_key": source_key,
        "status": status,
        "source_name": source_name,
        "normalized_source_name": (
            strict_legal_name(source_name) if source_name else None
        ),
        "matched_name": matched_name,
        "written": written,
        "response_sha": response_sha,
        "error": error,
        "next_retry_at": next_retry_at,
    })


def _gleif_candidates(batch_size: int, *, refresh: bool) -> list[dict[str, Any]]:
    with get_cortellis_session() as session:
        rows = session.execute(text("""
            SELECT company.id AS company_id,
                   company.name AS company_name,
                   xref.id AS xref_id,
                   xref.canonical_name,
                   ARRAY(
                       SELECT alias.alias_value
                       FROM company_aliases alias
                       WHERE alias.xref_id = xref.id
                         AND alias.alias_type IN (
                             'legal_name', 'former_legal_name',
                             'alternative_legal_name',
                             'transliterated_legal_name'
                         )
                       ORDER BY alias.id
                   ) AS aliases
            FROM company_xref xref
            JOIN companies company ON company.id = xref.cortellis_id
            LEFT JOIN company_identity_source_state state
              ON state.source = :source
             AND state.company_id = company.id
            WHERE :refresh
               OR state.company_id IS NULL
               OR (
                    state.status = 'failed'
                    AND COALESCE(state.next_retry_at, NOW()) <= NOW()
               )
               OR state.updated_at < NOW() - make_interval(days => :refresh_days)
            ORDER BY company.id
            LIMIT :limit
        """), {
            "source": GLEIF_STATE_SOURCE,
            "refresh": refresh,
            "refresh_days": settings.gleif_refresh_days,
            "limit": batch_size,
        }).mappings().all()
    return [dict(row) for row in rows]


def _record_attributes(record: dict[str, Any]) -> tuple[str, str, str, float]:
    attributes = record.get("attributes") or {}
    entity = attributes.get("entity") or {}
    registration = attributes.get("registration") or {}
    source_name = str((entity.get("legalName") or {}).get("name") or "").strip()
    corroboration = str(registration.get("corroborationLevel") or "")
    if corroboration == "FULLY_CORROBORATED":
        return source_name, corroboration, "verified", 1.0
    if corroboration == "PARTIALLY_CORROBORATED":
        return source_name, corroboration, "needs_review", 0.95
    return source_name, corroboration, "unreviewed", 0.85


def _upsert_lei_and_aliases(
    session,
    candidate: dict[str, Any],
    record: dict[str, Any],
    *,
    response_sha: str,
    request_url: str,
) -> tuple[str, int]:
    lei = normalize_lei(record.get("id") or record.get("attributes", {}).get("lei"))
    source_name, corroboration, review_status, confidence = _record_attributes(record)
    conflict = session.execute(text("""
        SELECT company_id FROM company_identifiers
        WHERE identifier_type = 'lei' AND normalized_value = :lei
    """), {"lei": lei}).scalar()
    if conflict is not None and int(conflict) != int(candidate["company_id"]):
        return "identifier_conflict", 0

    reviewed_by = (
        "GLEIF fully corroborated exact legal-name match"
        if review_status == "verified" else None
    )
    evidence = json.dumps({
        "gleif_legal_name": source_name,
        "local_names": _candidate_names(candidate),
        "corroboration_level": corroboration,
        "response_sha256": response_sha,
        "match_method": "strict_exact_legal_or_alternate_name",
    }, sort_keys=True)
    result = session.execute(text("""
        INSERT INTO company_identifiers (
            company_id, identifier_type, identifier_value, normalized_value,
            source, source_reference, evidence, confidence, review_status,
            reviewed_by, reviewed_at
        ) VALUES (
            :company_id, 'lei', :lei, :lei,
            :source, :source_reference, CAST(:evidence AS JSONB),
            :confidence, :review_status, :reviewed_by,
            CASE WHEN :reviewed_by IS NULL THEN NULL ELSE NOW() END
        ) ON CONFLICT (identifier_type, normalized_value) DO UPDATE SET
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
        "lei": lei,
        "source": GLEIF_RECORD_SOURCE,
        "source_reference": request_url,
        "evidence": evidence,
        "confidence": confidence,
        "review_status": review_status,
        "reviewed_by": reviewed_by,
    }).first()
    written = 1 if result else 0

    entity = (record.get("attributes") or {}).get("entity") or {}
    aliases: list[tuple[str, str]] = []
    for item in entity.get("otherNames") or []:
        aliases.append(("alternative_legal_name", str(item.get("name") or "")))
    for item in entity.get("transliteratedOtherNames") or []:
        aliases.append(("transliterated_legal_name", str(item.get("name") or "")))
    for alias_type, alias_value in aliases:
        alias_value = alias_value.strip()
        if not alias_value:
            continue
        session.execute(text("""
            INSERT INTO company_aliases (
                xref_id, alias_type, alias_value, source, normalized_value,
                source_reference, evidence, confidence, review_status,
                reviewed_by, reviewed_at
            ) VALUES (
                :xref_id, :alias_type, :alias_value, :source, :normalized,
                :source_reference, CAST(:evidence AS JSONB), :confidence,
                :review_status, :reviewed_by,
                CASE WHEN :reviewed_by IS NULL THEN NULL ELSE NOW() END
            ) ON CONFLICT DO NOTHING
        """), {
            "xref_id": candidate["xref_id"],
            "alias_type": alias_type,
            "alias_value": alias_value,
            "source": GLEIF_RECORD_SOURCE,
            "normalized": strict_legal_name(alias_value),
            "source_reference": request_url,
            "evidence": json.dumps({
                "lei": lei,
                "response_sha256": response_sha,
            }, sort_keys=True),
            "confidence": confidence,
            "review_status": review_status,
            "reviewed_by": reviewed_by,
        })
    return "matched", written


def enrich_gleif_company_identities(
    *,
    batch_size: int = 25,
    refresh: bool = False,
    client: GleifClient | None = None,
) -> dict[str, Any]:
    """Populate LEIs only for unique, strict exact-name GLEIF records."""
    ensure_sec_company_identity_schema()
    lock = get_cortellis_engine().connect()
    acquired = bool(lock.execute(text(
        "SELECT pg_try_advisory_lock(hashtext('onebd_gleif_company_identity'))"
    )).scalar())
    if not acquired:
        lock.close()
        return {"status": "skipped", "reason": "GLEIF identity scan running"}
    try:
        candidates = _gleif_candidates(batch_size, refresh=refresh)
        totals = {
            "processed": 0,
            "matched": 0,
            "no_match": 0,
            "ambiguous": 0,
            "inactive": 0,
            "truncated": 0,
            "identifier_conflicts": 0,
            "identifiers_written": 0,
            "failed": 0,
        }
        source_client = client or GleifClient()
        with get_cortellis_session() as session:
            for candidate in candidates:
                totals["processed"] += 1
                try:
                    outcome = "no_match"
                    selected = None
                    matched_name = None
                    response_sha = None
                    with session.begin_nested():
                        records: dict[str, dict[str, Any]] = {}
                        any_truncated = False
                        matched_truncated = False
                        for term in _search_terms(candidate):
                            response = source_client.search_legal_name(term)
                            search_key = (
                                f"{candidate['company_id']}:"
                                f"{hashlib.sha1(term.encode()).hexdigest()[:16]}"
                            )
                            response_sha = _archive_response(
                                session,
                                company_id=candidate["company_id"],
                                source=GLEIF_SEARCH_SOURCE,
                                source_key=search_key,
                                response=response,
                            )
                            data = response.payload.get("data") or []
                            pagination = (response.payload.get("meta") or {}).get(
                                "pagination"
                            ) or {}
                            response_truncated = (
                                int(pagination.get("total") or 0) > len(data)
                            )
                            any_truncated = any_truncated or response_truncated
                            for record in data:
                                if isinstance(record, dict) and record.get("id"):
                                    records[str(record["id"])] = record
                            outcome, selected, matched_name = select_unique_gleif_match(
                                list(records.values()),
                                _candidate_names(candidate),
                            )
                            if outcome in {"matched", "ambiguous"}:
                                matched_truncated = response_truncated
                                break

                        if (
                            (outcome == "matched" and matched_truncated)
                            or (outcome in {"no_match", "inactive"} and any_truncated)
                        ):
                            outcome = "truncated"
                            selected = None
                            matched_name = None

                        written = 0
                        source_name = None
                        source_key = str(candidate["company_id"])
                        if selected is not None:
                            lei = normalize_lei(selected.get("id"))
                            record_response = source_client.record(lei)
                            response_sha = _archive_response(
                                session,
                                company_id=candidate["company_id"],
                                source=GLEIF_RECORD_SOURCE,
                                source_key=lei,
                                response=record_response,
                            )
                            record = record_response.payload.get("data") or {}
                            verify_outcome, verified, verified_name = (
                                select_unique_gleif_match(
                                    [record],
                                    _candidate_names(candidate),
                                )
                            )
                            if verify_outcome != "matched" or verified is None:
                                outcome = verify_outcome
                            else:
                                matched_name = verified_name or matched_name
                                source_name = gleif_record_names(verified)[0]
                                outcome, written = _upsert_lei_and_aliases(
                                    session,
                                    candidate,
                                    verified,
                                    response_sha=response_sha,
                                    request_url=record_response.request_url,
                                )
                                source_key = lei

                        _record_state(
                            session,
                            candidate,
                            source=GLEIF_STATE_SOURCE,
                            status=outcome,
                            source_key=source_key,
                            source_name=source_name,
                            matched_name=matched_name,
                            written=written,
                            response_sha=response_sha,
                        )
                    if outcome == "matched":
                        totals["matched"] += 1
                        totals["identifiers_written"] += written
                    elif outcome == "identifier_conflict":
                        totals["identifier_conflicts"] += 1
                    else:
                        totals[outcome] += 1
                except Exception as exc:  # noqa: BLE001 - durable per-record state
                    totals["failed"] += 1
                    with session.begin_nested():
                        _record_state(
                            session,
                            candidate,
                            source=GLEIF_STATE_SOURCE,
                            status="failed",
                            source_key=str(candidate["company_id"]),
                            error=str(exc)[:2000],
                        )
                # Do not retain row or DDL-conflicting locks while the next
                # company is fetched from the external API. Each candidate is
                # an independent durable checkpoint, so a killed accelerator
                # can resume without replaying the rest of this batch.
                session.commit()
        return {"status": "partial" if totals["failed"] else "completed", **totals}
    finally:
        try:
            lock.execute(text(
                "SELECT pg_advisory_unlock(hashtext('onebd_gleif_company_identity'))"
            ))
        finally:
            lock.close()


def _ownership_candidates(batch_size: int, *, refresh: bool) -> list[dict[str, Any]]:
    with get_cortellis_session() as session:
        rows = session.execute(text("""
            SELECT company.id AS company_id, company.name AS company_name,
                   identifier.normalized_value AS lei
            FROM company_identifiers identifier
            JOIN companies company ON company.id = identifier.company_id
            LEFT JOIN company_identity_source_state state
              ON state.source = :state_source
             AND state.company_id = company.id
            WHERE identifier.identifier_type = 'lei'
              AND identifier.source IN (:gleif_source, :sec_source)
              AND identifier.review_status = 'verified'
              AND (
                  :refresh
                  OR state.company_id IS NULL
                  OR (
                      state.status = 'failed'
                      AND COALESCE(state.next_retry_at, NOW()) <= NOW()
                  )
                  OR state.updated_at < NOW() - make_interval(days => :refresh_days)
              )
            ORDER BY company.id
            LIMIT :limit
        """), {
            "state_source": GLEIF_OWNERSHIP_SOURCE,
            "gleif_source": GLEIF_RECORD_SOURCE,
            "sec_source": SEC_SUBMISSIONS_SOURCE,
            "refresh": refresh,
            "refresh_days": settings.gleif_refresh_days,
            "limit": batch_size,
        }).mappings().all()
    return [dict(row) for row in rows]


def _relationship_links(record: dict[str, Any]) -> tuple[str, str] | None:
    direct_parent = (record.get("relationships") or {}).get("direct-parent") or {}
    links = direct_parent.get("links") or {}
    parent_url = links.get("lei-record")
    relationship_url = links.get("relationship-record")
    if not parent_url or not relationship_url:
        return None
    return str(parent_url), str(relationship_url)


def _iso_date(value: Any) -> str | None:
    raw = str(value or "").strip()
    return raw[:10] if re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", raw) else None


def _upsert_ownership(
    session,
    candidate: dict[str, Any],
    parent_record: dict[str, Any],
    relationship_record: dict[str, Any],
    *,
    request_url: str,
    response_sha: str,
) -> tuple[str, int, str, str | None]:
    child_lei = normalize_lei(candidate["lei"])
    parent_lei = normalize_lei(
        parent_record.get("id") or parent_record.get("attributes", {}).get("lei")
    )
    attributes = relationship_record.get("attributes") or {}
    relationship = attributes.get("relationship") or {}
    start = relationship.get("startNode") or {}
    end = relationship.get("endNode") or {}
    if (
        normalize_lei(start.get("id")) != child_lei
        or normalize_lei(end.get("id")) != parent_lei
        or relationship.get("type") != "IS_DIRECTLY_CONSOLIDATED_BY"
    ):
        raise ValueError("GLEIF direct-parent relationship nodes/type did not agree")
    parent_name = gleif_record_names(parent_record)[0]
    if relationship.get("status") != "ACTIVE":
        return "inactive", 0, parent_lei, parent_name

    parent_company_id = session.execute(text("""
        SELECT company_id FROM company_identifiers
        WHERE identifier_type = 'lei' AND normalized_value = :lei
          AND review_status = 'verified'
    """), {"lei": parent_lei}).scalar()
    if parent_company_id is None:
        return "parent_not_local", 0, parent_lei, parent_name
    if int(parent_company_id) == int(candidate["company_id"]):
        raise ValueError("GLEIF ownership relationship points company to itself")

    registration = attributes.get("registration") or {}
    corroboration = str(registration.get("corroborationLevel") or "")
    registration_status = str(registration.get("status") or "")
    if corroboration == "FULLY_CORROBORATED" and registration_status == "PUBLISHED":
        review_status = "verified"
        confidence = 1.0
        reviewed_by = "GLEIF fully corroborated Level 2 relationship"
    elif corroboration == "PARTIALLY_CORROBORATED":
        review_status = "needs_review"
        confidence = 0.9
        reviewed_by = None
    else:
        review_status = "unreviewed"
        confidence = 0.7
        reviewed_by = None

    periods = relationship.get("periods") or []
    relationship_period = next(
        (period for period in periods if period.get("type") == "RELATIONSHIP_PERIOD"),
        {},
    )
    effective_from = _iso_date(
        relationship_period.get("startDate") or attributes.get("validFrom")
    )
    effective_to = _iso_date(
        relationship_period.get("endDate") or attributes.get("validTo")
    )
    evidence = json.dumps({
        "child_lei": child_lei,
        "parent_lei": parent_lei,
        "gleif_relationship_id": relationship_record.get("id"),
        "relationship_status": relationship.get("status"),
        "registration_status": registration_status,
        "corroboration_level": corroboration,
        "corroboration_documents": registration.get("corroborationDocuments"),
        "corroboration_reference": registration.get("corroborationReference"),
        "response_sha256": response_sha,
    }, sort_keys=True)
    result = session.execute(text("""
        INSERT INTO company_identity_relationships (
            parent_company_id, child_company_id, relationship_type,
            effective_from, effective_to, source, source_reference,
            evidence, confidence, review_status, reviewed_by, reviewed_at
        ) VALUES (
            :parent_company_id, :child_company_id,
            'direct_accounting_consolidating_parent',
            CAST(:effective_from AS DATE), CAST(:effective_to AS DATE),
            :source, :source_reference, CAST(:evidence AS JSONB),
            :confidence, :review_status, :reviewed_by,
            CASE WHEN :reviewed_by IS NULL THEN NULL ELSE NOW() END
        ) ON CONFLICT (
            parent_company_id, child_company_id, relationship_type
        ) DO UPDATE SET
            effective_from = EXCLUDED.effective_from,
            effective_to = EXCLUDED.effective_to,
            source = EXCLUDED.source,
            source_reference = EXCLUDED.source_reference,
            evidence = EXCLUDED.evidence,
            confidence = EXCLUDED.confidence,
            review_status = EXCLUDED.review_status,
            reviewed_by = EXCLUDED.reviewed_by,
            reviewed_at = EXCLUDED.reviewed_at,
            updated_at = NOW()
        RETURNING id
    """), {
        "parent_company_id": parent_company_id,
        "child_company_id": candidate["company_id"],
        "effective_from": effective_from,
        "effective_to": effective_to,
        "source": GLEIF_RELATIONSHIP_SOURCE,
        "source_reference": request_url,
        "evidence": evidence,
        "confidence": confidence,
        "review_status": review_status,
        "reviewed_by": reviewed_by,
    }).first()
    return "matched", 1 if result else 0, parent_lei, parent_name


def enrich_gleif_company_ownership(
    *,
    batch_size: int = 50,
    refresh: bool = False,
    client: GleifClient | None = None,
) -> dict[str, Any]:
    """Retain GLEIF direct parents only when both LEIs map to local companies."""
    ensure_sec_company_identity_schema()
    lock = get_cortellis_engine().connect()
    acquired = bool(lock.execute(text(
        "SELECT pg_try_advisory_lock(hashtext('onebd_gleif_company_ownership'))"
    )).scalar())
    if not acquired:
        lock.close()
        return {"status": "skipped", "reason": "GLEIF ownership scan running"}
    try:
        candidates = _ownership_candidates(batch_size, refresh=refresh)
        totals = {
            "processed": 0,
            "matched": 0,
            "no_parent": 0,
            "parent_not_local": 0,
            "inactive": 0,
            "relationships_written": 0,
            "failed": 0,
        }
        source_client = client or GleifClient()
        with get_cortellis_session() as session:
            for candidate in candidates:
                totals["processed"] += 1
                try:
                    with session.begin_nested():
                        lei = normalize_lei(candidate["lei"])
                        record_response = source_client.record(lei)
                        record = record_response.payload.get("data") or {}
                        links = _relationship_links(record)
                        response_sha = _archive_response(
                            session,
                            company_id=candidate["company_id"],
                            source=GLEIF_OWNERSHIP_SOURCE,
                            source_key=f"{lei}:record",
                            response=record_response,
                        )
                        if not links:
                            outcome = "no_parent"
                            written = 0
                            parent_lei = None
                            parent_name = None
                            relationship_sha = response_sha
                        else:
                            parent_response = source_client.related(links[0])
                            relationship_response = source_client.related(links[1])
                            parent_record = parent_response.payload.get("data") or {}
                            relationship_record = (
                                relationship_response.payload.get("data") or {}
                            )
                            _archive_response(
                                session,
                                company_id=candidate["company_id"],
                                source=GLEIF_OWNERSHIP_SOURCE,
                                source_key=f"{lei}:parent",
                                response=parent_response,
                            )
                            relationship_sha = _archive_response(
                                session,
                                company_id=candidate["company_id"],
                                source=GLEIF_OWNERSHIP_SOURCE,
                                source_key=f"{lei}:relationship",
                                response=relationship_response,
                            )
                            outcome, written, parent_lei, parent_name = _upsert_ownership(
                                session,
                                candidate,
                                parent_record,
                                relationship_record,
                                request_url=relationship_response.request_url,
                                response_sha=relationship_sha,
                            )
                        _record_state(
                            session,
                            candidate,
                            source=GLEIF_OWNERSHIP_SOURCE,
                            status=outcome,
                            source_key=lei,
                            source_name=parent_name,
                            matched_name=parent_lei,
                            written=written,
                            response_sha=relationship_sha,
                        )
                    totals[outcome] += 1
                    totals["relationships_written"] += written
                except Exception as exc:  # noqa: BLE001 - durable per-record state
                    totals["failed"] += 1
                    with session.begin_nested():
                        _record_state(
                            session,
                            candidate,
                            source=GLEIF_OWNERSHIP_SOURCE,
                            status="failed",
                            source_key=str(candidate.get("lei") or candidate["company_id"]),
                            error=str(exc)[:2000],
                        )
                # Level 2 lookups make multiple external requests. Release
                # database locks between companies instead of holding one
                # transaction for the entire scheduled batch.
                session.commit()
        return {"status": "partial" if totals["failed"] else "completed", **totals}
    finally:
        try:
            lock.execute(text(
                "SELECT pg_advisory_unlock(hashtext('onebd_gleif_company_ownership'))"
            ))
        finally:
            lock.close()


def gleif_company_identity_status() -> dict[str, Any]:
    """Return GLEIF LEI/ownership coverage and review-state counts."""
    ensure_sec_company_identity_schema()
    with get_cortellis_session() as session:
        identity = session.execute(text("""
            SELECT
              (SELECT COUNT(*) FROM company_xref
               WHERE cortellis_id IS NOT NULL) AS eligible,
              COUNT(*) AS scanned,
              COUNT(*) FILTER (WHERE status = 'matched') AS matched,
              COUNT(*) FILTER (WHERE status = 'no_match') AS no_match,
              COUNT(*) FILTER (WHERE status = 'ambiguous') AS ambiguous,
              COUNT(*) FILTER (WHERE status = 'inactive') AS inactive,
              COUNT(*) FILTER (WHERE status = 'truncated') AS truncated,
              COUNT(*) FILTER (WHERE status = 'identifier_conflict') AS conflicts,
              COUNT(*) FILTER (WHERE status = 'failed') AS failed,
              MAX(last_attempt_at) AS last_attempt_at
            FROM company_identity_source_state
            WHERE source = :source
        """), {"source": GLEIF_STATE_SOURCE}).mappings().one()
        identifiers = session.execute(text("""
            SELECT review_status, COUNT(*) AS records
            FROM company_identifiers
            WHERE identifier_type = 'lei' AND source = :source
            GROUP BY review_status ORDER BY review_status
        """), {"source": GLEIF_RECORD_SOURCE}).mappings().all()
        ownership = session.execute(text("""
            SELECT status, COUNT(*) AS records
            FROM company_identity_source_state
            WHERE source = :source
            GROUP BY status ORDER BY status
        """), {"source": GLEIF_OWNERSHIP_SOURCE}).mappings().all()
        relationships = session.execute(text("""
            SELECT review_status, COUNT(*) AS records
            FROM company_identity_relationships
            WHERE source = :source
            GROUP BY review_status ORDER BY review_status
        """), {"source": GLEIF_RELATIONSHIP_SOURCE}).mappings().all()
    result = dict(identity)
    result["coverage_pct"] = round(
        100 * int(identity["scanned"] or 0) / max(1, int(identity["eligible"] or 0)),
        2,
    )
    result["identifiers"] = [dict(row) for row in identifiers]
    result["ownership_states"] = [dict(row) for row in ownership]
    result["relationships"] = [dict(row) for row in relationships]
    result["source"] = GLEIF_RECORD_SOURCE
    return result
