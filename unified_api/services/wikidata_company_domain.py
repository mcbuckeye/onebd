"""Exact-LEI Wikidata company-domain enrichment."""

from __future__ import annotations

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
from unified_api.services.entity_resolution import normalize_identifier_value
from unified_api.services.gleif_company_identity import (
    GLEIF_RECORD_SOURCE,
    _archive_response,
    _record_state,
    normalize_lei,
)
from unified_api.services.public_source_http import (
    PublicSourceHttpClient,
    RetryPolicy,
)
from unified_api.services.sec_company_identity import (
    SEC_SUBMISSIONS_SOURCE,
    ensure_sec_company_identity_schema,
)


WIKIDATA_DOMAIN_SOURCE = "wikidata_lei_domain"
WIKIDATA_DOMAIN_STATE_SOURCE = "wikidata_company_domain"
_item_pattern = re.compile(r"Q[1-9][0-9]*\Z")


class WikidataDomainClient:
    """Query Wikidata official websites using exact LEI property P1278."""

    def __init__(self, *, base_url: str | None = None):
        self._http = PublicSourceHttpClient(
            source=WIKIDATA_DOMAIN_SOURCE,
            base_url=(base_url or settings.wikidata_query_url).rstrip("/"),
            user_agent=settings.public_data_user_agent,
            timeout=30,
            min_interval_seconds=settings.wikidata_request_interval_seconds,
            retry_policy=RetryPolicy(max_retries=3),
        )

    def domains_for_lei(self, lei: str):
        normalized = normalize_lei(lei)
        query = f"""SELECT ?item ?website WHERE {{
  ?item wdt:P1278 \"{normalized}\" .
  OPTIONAL {{ ?item wdt:P856 ?website . }}
}}"""
        response = self._http.get_json(
            "/sparql",
            {"query": query, "format": "json"},
        )
        if response is None:
            raise RuntimeError(f"Wikidata returned no response for LEI {normalized}")
        return response


def parse_wikidata_domains(
    payload: dict[str, Any],
) -> tuple[str, str | None, list[dict[str, str]]]:
    """Return one unambiguous Wikidata item and its validated web domains."""
    bindings = ((payload.get("results") or {}).get("bindings") or [])
    items: set[str] = set()
    domains: dict[str, dict[str, str]] = {}
    for binding in bindings:
        item_url = str(((binding.get("item") or {}).get("value")) or "")
        parsed_item = urlsplit(item_url)
        item_id = parsed_item.path.rsplit("/", 1)[-1]
        if (
            parsed_item.scheme != "http"
            or parsed_item.hostname != "www.wikidata.org"
            or not _item_pattern.fullmatch(item_id)
        ):
            raise ValueError(f"Unexpected Wikidata item URI: {item_url}")
        items.add(item_id)

        website = str(((binding.get("website") or {}).get("value")) or "").strip()
        if not website:
            continue
        parsed_website = urlsplit(website)
        domain = normalize_identifier_value("domain", website)
        if (
            parsed_website.scheme not in {"http", "https"}
            or not domain
            or "." not in domain
            or " " in domain
        ):
            raise ValueError(f"Unexpected Wikidata official website: {website}")
        domains[domain] = {
            "identifier_type": "domain",
            "identifier_value": website,
            "normalized_value": domain,
        }

    if not items:
        return "no_match", None, []
    if len(items) > 1:
        return "ambiguous", None, []
    item_id = next(iter(items))
    if not domains:
        return "no_domain", item_id, []
    return "matched", item_id, list(domains.values())


def _domain_candidates(batch_size: int, *, refresh: bool) -> list[dict[str, Any]]:
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
            "state_source": WIKIDATA_DOMAIN_STATE_SOURCE,
            "gleif_source": GLEIF_RECORD_SOURCE,
            "sec_source": SEC_SUBMISSIONS_SOURCE,
            "refresh": refresh,
            "refresh_days": settings.wikidata_refresh_days,
            "limit": batch_size,
        }).mappings().all()
    return [dict(row) for row in rows]


def _upsert_domains(
    session,
    candidate: dict[str, Any],
    domains: list[dict[str, str]],
    *,
    item_id: str,
    response_sha: str,
    request_url: str,
) -> tuple[str, int]:
    normalized_domains = [domain["normalized_value"] for domain in domains]
    conflicts = session.execute(text("""
        SELECT normalized_value, company_id
        FROM company_identifiers
        WHERE identifier_type = 'domain'
          AND normalized_value = ANY(:domains)
          AND company_id <> :company_id
    """), {
        "domains": normalized_domains,
        "company_id": candidate["company_id"],
    }).mappings().all()
    if conflicts:
        return "shared_domain", 0

    written = 0
    for domain in domains:
        evidence = json.dumps({
            "lei": candidate["lei"],
            "wikidata_item": item_id,
            "wikidata_property": "P856",
            "lei_property": "P1278",
            "response_sha256": response_sha,
            "match_method": "exact_lei",
        }, sort_keys=True)
        result = session.execute(text("""
            INSERT INTO company_identifiers (
                company_id, identifier_type, identifier_value,
                normalized_value, source, source_reference, evidence,
                confidence, review_status
            ) VALUES (
                :company_id, 'domain', :identifier_value,
                :normalized_value, :source, :source_reference,
                CAST(:evidence AS JSONB), 0.9, 'needs_review'
            ) ON CONFLICT (identifier_type, normalized_value) DO NOTHING
            RETURNING id
        """), {
            "company_id": candidate["company_id"],
            "identifier_value": domain["identifier_value"],
            "normalized_value": domain["normalized_value"],
            "source": WIKIDATA_DOMAIN_SOURCE,
            "source_reference": request_url,
            "evidence": evidence,
        }).first()
        if result:
            written += 1
    return "matched", written


def enrich_wikidata_company_domains(
    *,
    batch_size: int = 50,
    refresh: bool = False,
    client: WikidataDomainClient | None = None,
) -> dict[str, Any]:
    """Populate reviewable official domains through exact LEI joins."""
    ensure_sec_company_identity_schema()
    lock = get_cortellis_engine().connect()
    acquired = bool(lock.execute(text(
        "SELECT pg_try_advisory_lock(hashtext('onebd_wikidata_company_domain'))"
    )).scalar())
    if not acquired:
        lock.close()
        return {"status": "skipped", "reason": "Wikidata domain scan running"}
    try:
        candidates = _domain_candidates(batch_size, refresh=refresh)
        totals = {
            "processed": 0,
            "matched": 0,
            "no_match": 0,
            "no_domain": 0,
            "ambiguous": 0,
            "shared_domain": 0,
            "domains_written": 0,
            "failed": 0,
        }
        source_client = client or WikidataDomainClient()
        with get_cortellis_session() as session:
            for candidate in candidates:
                totals["processed"] += 1
                try:
                    with session.begin_nested():
                        lei = normalize_lei(candidate["lei"])
                        response = source_client.domains_for_lei(lei)
                        response_sha = _archive_response(
                            session,
                            company_id=candidate["company_id"],
                            source=WIKIDATA_DOMAIN_SOURCE,
                            source_key=lei,
                            response=response,
                        )
                        outcome, item_id, domains = parse_wikidata_domains(
                            response.payload
                        )
                        written = 0
                        if outcome == "matched" and item_id:
                            outcome, written = _upsert_domains(
                                session,
                                candidate,
                                domains,
                                item_id=item_id,
                                response_sha=response_sha,
                                request_url=response.request_url,
                            )
                        _record_state(
                            session,
                            candidate,
                            source=WIKIDATA_DOMAIN_STATE_SOURCE,
                            status=outcome,
                            source_key=lei,
                            source_name=item_id,
                            matched_name=(
                                ",".join(
                                    domain["normalized_value"] for domain in domains
                                ) or None
                            ),
                            written=written,
                            response_sha=response_sha,
                        )
                    totals[outcome] += 1
                    totals["domains_written"] += written
                except Exception as exc:  # noqa: BLE001 - durable per-record state
                    totals["failed"] += 1
                    with session.begin_nested():
                        _record_state(
                            session,
                            candidate,
                            source=WIKIDATA_DOMAIN_STATE_SOURCE,
                            status="failed",
                            source_key=str(candidate.get("lei") or candidate["company_id"]),
                            error=str(exc)[:2000],
                        )
        return {"status": "partial" if totals["failed"] else "completed", **totals}
    finally:
        try:
            lock.execute(text(
                "SELECT pg_advisory_unlock(hashtext('onebd_wikidata_company_domain'))"
            ))
        finally:
            lock.close()


def wikidata_company_domain_status() -> dict[str, Any]:
    """Return exact-LEI Wikidata domain coverage and review state."""
    ensure_sec_company_identity_schema()
    with get_cortellis_session() as session:
        summary = session.execute(text("""
            SELECT
              (SELECT COUNT(*) FROM company_identifiers
               WHERE identifier_type = 'lei'
                 AND source IN (:gleif_source, :sec_source)
                 AND review_status = 'verified') AS eligible,
              COUNT(*) AS scanned,
              COUNT(*) FILTER (WHERE status = 'matched') AS matched,
              COUNT(*) FILTER (WHERE status = 'no_match') AS no_match,
              COUNT(*) FILTER (WHERE status = 'no_domain') AS no_domain,
              COUNT(*) FILTER (WHERE status = 'ambiguous') AS ambiguous,
              COUNT(*) FILTER (WHERE status = 'shared_domain') AS shared_domain,
              COUNT(*) FILTER (WHERE status = 'failed') AS failed,
              MAX(last_attempt_at) AS last_attempt_at
            FROM company_identity_source_state
            WHERE source = :state_source
        """), {
            "gleif_source": GLEIF_RECORD_SOURCE,
            "sec_source": SEC_SUBMISSIONS_SOURCE,
            "state_source": WIKIDATA_DOMAIN_STATE_SOURCE,
        }).mappings().one()
        identifiers = session.execute(text("""
            SELECT review_status, COUNT(*) AS records
            FROM company_identifiers
            WHERE identifier_type = 'domain' AND source = :source
            GROUP BY review_status ORDER BY review_status
        """), {"source": WIKIDATA_DOMAIN_SOURCE}).mappings().all()
    result = dict(summary)
    result["coverage_pct"] = round(
        100 * int(summary["scanned"] or 0) / max(1, int(summary["eligible"] or 0)),
        2,
    )
    result["identifiers"] = [dict(row) for row in identifiers]
    result["source"] = WIKIDATA_DOMAIN_SOURCE
    return result
