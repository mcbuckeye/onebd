"""Exact target-literature evidence from the official Europe PMC REST API."""

from __future__ import annotations

from datetime import date
import hashlib
import html
import json
import re
from typing import Any

from sqlalchemy import text

from unified_api.config import settings
from unified_api.services.database import (
    get_cortellis_engine,
    get_cortellis_session,
)
from unified_api.services.public_source_http import (
    PublicSourceHttpClient,
    RetryPolicy,
)
from unified_api.services.uniprot_enrichment import (
    UNIPROT_ACCESSION_PATTERN,
    ensure_public_target_schema,
)


EUROPE_PMC_SOURCE = "europe_pmc_rest"
_uniprot_accession = re.compile(rf"{UNIPROT_ACCESSION_PATTERN}\Z")
_ensembl_id = re.compile(r"ENSG\d{11}\Z")
_europe_pmc_schema_ready = False


def exact_target_query(*, accession: str, ensembl_id: str) -> str:
    """Build a structured query from identifiers already verified upstream."""
    accession = accession.upper()
    ensembl_id = ensembl_id.upper()
    if not _uniprot_accession.fullmatch(accession):
        raise ValueError(f"Invalid UniProt accession: {accession}")
    if not _ensembl_id.fullmatch(ensembl_id):
        raise ValueError(f"Invalid Ensembl target ID: {ensembl_id}")
    return (
        f"((ACCESSION_TYPE:uniprot) AND (ACCESSION_ID:{accession})) "
        f"OR UNIPROT_PUBS:{accession} OR "
        f"((ACCESSION_TYPE:ensembl) AND (ACCESSION_ID:{ensembl_id}))"
    )


class EuropePmcClient:
    """Cursor-paginated adapter for structured Europe PMC target queries."""

    def __init__(self, *, base_url: str | None = None):
        self._http = PublicSourceHttpClient(
            source=EUROPE_PMC_SOURCE,
            base_url=base_url or settings.europe_pmc_base_url,
            user_agent=settings.public_data_user_agent,
            timeout=90,
            min_interval_seconds=settings.europe_pmc_request_interval_seconds,
            retry_policy=RetryPolicy(max_retries=3),
        )

    def target_publications(
        self,
        *,
        accession: str,
        ensembl_id: str,
        cursor_mark: str = "*",
        page_size: int | None = None,
    ) -> dict[str, Any]:
        query = exact_target_query(
            accession=accession,
            ensembl_id=ensembl_id,
        )
        page_size = page_size or settings.europe_pmc_page_size
        if not 1 <= page_size <= 1000:
            raise ValueError("Europe PMC page size must be between 1 and 1000")
        response = self._http.get_json("/search", {
            "query": query,
            "format": "json",
            "resultType": "core",
            "pageSize": page_size,
            "cursorMark": cursor_mark,
            "sort": "CITED desc",
        })
        if response is None:
            raise RuntimeError("Europe PMC response was empty")
        payload = response.payload
        results = (payload.get("resultList") or {}).get("result") or []
        if not isinstance(results, list):
            raise ValueError("Europe PMC returned a non-list result payload")
        request_query = (payload.get("request") or {}).get("queryString")
        if request_query != query:
            raise ValueError("Europe PMC did not execute the exact target query")
        hit_count = int(payload.get("hitCount") or 0)
        if hit_count < len(results):
            raise ValueError("Europe PMC result count is internally inconsistent")
        for result in results:
            if not result.get("id") or not result.get("source"):
                raise ValueError("Europe PMC publication omitted its source ID")
        return payload


def ensure_europe_pmc_schema() -> None:
    """Create resumable query state and provenance-preserving literature tables."""
    global _europe_pmc_schema_ready
    if _europe_pmc_schema_ready:
        return
    from unified_api.services.runtime_schema import runtime_schema_is_pre_migrated

    if runtime_schema_is_pre_migrated():
        _europe_pmc_schema_ready = True
        return
    ensure_public_target_schema()
    with get_cortellis_session() as session:
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS public_literature_records (
                article_source VARCHAR(30) NOT NULL,
                external_id VARCHAR(100) NOT NULL,
                pmid VARCHAR(30),
                pmcid VARCHAR(30),
                doi TEXT,
                title TEXT NOT NULL,
                abstract_text TEXT,
                author_string TEXT,
                journal_title TEXT,
                publication_year INTEGER,
                first_publication_date DATE,
                publication_types JSONB NOT NULL DEFAULT '[]'::jsonb,
                mesh_headings JSONB NOT NULL DEFAULT '[]'::jsonb,
                chemicals JSONB NOT NULL DEFAULT '[]'::jsonb,
                cited_by_count INTEGER,
                is_open_access BOOLEAN,
                in_europe_pmc BOOLEAN,
                source VARCHAR(100) NOT NULL,
                source_version VARCHAR(50) NOT NULL,
                source_url TEXT NOT NULL,
                raw_sha256 CHAR(64) NOT NULL,
                raw_payload JSONB NOT NULL,
                first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (article_source, external_id)
            )
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_public_literature_date_citations
            ON public_literature_records (
                first_publication_date DESC, cited_by_count DESC
            )
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS public_literature_record_history (
                article_source VARCHAR(30) NOT NULL,
                external_id VARCHAR(100) NOT NULL,
                response_sha256 CHAR(64) NOT NULL,
                source_version VARCHAR(50) NOT NULL,
                raw_payload JSONB NOT NULL,
                first_fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (article_source, external_id, response_sha256)
            )
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS public_target_literature_links (
                ensembl_id VARCHAR(30) NOT NULL,
                requested_accession VARCHAR(20) NOT NULL,
                article_source VARCHAR(30) NOT NULL,
                external_id VARCHAR(100) NOT NULL,
                match_method VARCHAR(100) NOT NULL,
                source_query TEXT NOT NULL,
                source VARCHAR(100) NOT NULL,
                source_version VARCHAR(50) NOT NULL,
                first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (
                    ensembl_id, requested_accession,
                    article_source, external_id
                ),
                FOREIGN KEY (ensembl_id, requested_accession)
                    REFERENCES public_target_uniprot_records (
                        ensembl_id, requested_accession
                    ) ON DELETE CASCADE,
                FOREIGN KEY (article_source, external_id)
                    REFERENCES public_literature_records (
                        article_source, external_id
                    ) ON DELETE CASCADE
            )
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_public_target_literature_target
            ON public_target_literature_links (ensembl_id, requested_accession)
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS public_target_literature_state (
                ensembl_id VARCHAR(30) NOT NULL,
                requested_accession VARCHAR(20) NOT NULL,
                source VARCHAR(100) NOT NULL,
                source_query TEXT NOT NULL,
                query_hash CHAR(64) NOT NULL,
                status VARCHAR(20) NOT NULL,
                cursor_mark TEXT,
                hit_count BIGINT,
                processed_results BIGINT NOT NULL DEFAULT 0,
                pages_fetched INTEGER NOT NULL DEFAULT 0,
                attempts INTEGER NOT NULL DEFAULT 0,
                source_version VARCHAR(50),
                last_error TEXT,
                last_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                next_retry_at TIMESTAMPTZ,
                next_refresh_at TIMESTAMPTZ,
                PRIMARY KEY (ensembl_id, requested_accession, source),
                FOREIGN KEY (ensembl_id, requested_accession)
                    REFERENCES public_target_uniprot_records (
                        ensembl_id, requested_accession
                    ) ON DELETE CASCADE
            )
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_public_target_literature_state_queue
            ON public_target_literature_state (
                source, status, next_retry_at, next_refresh_at, ensembl_id
            )
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS europe_pmc_response_history (
                query_hash CHAR(64) NOT NULL,
                cursor_mark TEXT NOT NULL,
                response_sha256 CHAR(64) NOT NULL,
                source_query TEXT NOT NULL,
                source_version VARCHAR(50) NOT NULL,
                raw_payload JSONB NOT NULL,
                first_fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (query_hash, cursor_mark, response_sha256)
            )
        """))
    _europe_pmc_schema_ready = True


def _candidate() -> dict[str, Any] | None:
    with get_cortellis_session() as session:
        row = session.execute(text("""
            SELECT record.ensembl_id, record.requested_accession AS accession,
                   state.status, state.cursor_mark, state.hit_count,
                   state.processed_results, state.pages_fetched
            FROM public_target_uniprot_records record
            LEFT JOIN public_target_literature_state state
              ON state.ensembl_id = record.ensembl_id
             AND state.requested_accession = record.requested_accession
             AND state.source = :source
            WHERE state.ensembl_id IS NULL
               OR state.status IN ('pending', 'in_progress')
               OR (state.status = 'failed' AND state.attempts < 3
                   AND state.next_retry_at <= NOW())
               OR (state.status = 'complete' AND state.next_refresh_at <= NOW())
            ORDER BY
              CASE state.status
                WHEN 'in_progress' THEN 0
                WHEN 'pending' THEN 1
                WHEN 'failed' THEN 2
                WHEN 'complete' THEN 4
                ELSE 3
              END,
              record.ensembl_id, record.requested_accession
            LIMIT 1
        """), {"source": EUROPE_PMC_SOURCE}).mappings().first()
    if not row:
        return None
    result = dict(row)
    refreshing = result.get("status") == "complete"
    if refreshing:
        result.update({
            "cursor_mark": "*",
            "hit_count": None,
            "processed_results": 0,
            "pages_fetched": 0,
        })
    else:
        result["cursor_mark"] = result.get("cursor_mark") or "*"
    return result


def _date_or_none(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _yes(value: Any) -> bool | None:
    if value is None:
        return None
    return str(value).upper() in {"Y", "YES", "TRUE", "1"}


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _plain_text(value: Any) -> str | None:
    if not value:
        return None
    decoded = html.unescape(str(value))
    return re.sub(r"<[^>]+>", "", decoded).strip() or None


def _publication_values(result: dict[str, Any], source_version: str) -> dict[str, Any]:
    article_source = str(result["source"]).upper()
    external_id = str(result["id"])
    raw_json = json.dumps(result, sort_keys=True, separators=(",", ":"))
    raw_sha = hashlib.sha256(raw_json.encode()).hexdigest()
    journal = ((result.get("journalInfo") or {}).get("journal") or {})
    title = _plain_text(result.get("title")) or external_id
    return {
        "article_source": article_source,
        "external_id": external_id,
        "pmid": result.get("pmid"),
        "pmcid": result.get("pmcid"),
        "doi": result.get("doi"),
        "title": title,
        "abstract_text": _plain_text(result.get("abstractText")),
        "author_string": result.get("authorString"),
        "journal_title": journal.get("title"),
        "publication_year": _int_or_none(result.get("pubYear")),
        "first_publication_date": _date_or_none(
            result.get("firstPublicationDate")
        ),
        "publication_types": json.dumps(
            (result.get("pubTypeList") or {}).get("pubType") or []
        ),
        "mesh_headings": json.dumps(
            (result.get("meshHeadingList") or {}).get("meshHeading") or []
        ),
        "chemicals": json.dumps(
            (result.get("chemicalList") or {}).get("chemical") or []
        ),
        "cited_by_count": _int_or_none(result.get("citedByCount")),
        "is_open_access": _yes(result.get("isOpenAccess")),
        "in_europe_pmc": _yes(result.get("inEPMC")),
        "source": EUROPE_PMC_SOURCE,
        "source_version": source_version,
        "source_url": (
            f"https://europepmc.org/article/{article_source}/{external_id}"
        ),
        "raw_sha": raw_sha,
        "raw_payload": raw_json,
    }


def _upsert_publication(
    session,
    *,
    result: dict[str, Any],
    source_version: str,
) -> dict[str, Any]:
    values = _publication_values(result, source_version)
    session.execute(text("""
        INSERT INTO public_literature_records (
            article_source, external_id, pmid, pmcid, doi, title,
            abstract_text, author_string, journal_title, publication_year,
            first_publication_date, publication_types, mesh_headings,
            chemicals, cited_by_count, is_open_access, in_europe_pmc,
            source, source_version, source_url, raw_sha256, raw_payload
        ) VALUES (
            :article_source, :external_id, :pmid, :pmcid, :doi, :title,
            :abstract_text, :author_string, :journal_title, :publication_year,
            :first_publication_date, CAST(:publication_types AS JSONB),
            CAST(:mesh_headings AS JSONB), CAST(:chemicals AS JSONB),
            :cited_by_count, :is_open_access, :in_europe_pmc,
            :source, :source_version, :source_url, :raw_sha,
            CAST(:raw_payload AS JSONB)
        ) ON CONFLICT (article_source, external_id) DO UPDATE SET
            pmid = EXCLUDED.pmid,
            pmcid = EXCLUDED.pmcid,
            doi = EXCLUDED.doi,
            title = EXCLUDED.title,
            abstract_text = EXCLUDED.abstract_text,
            author_string = EXCLUDED.author_string,
            journal_title = EXCLUDED.journal_title,
            publication_year = EXCLUDED.publication_year,
            first_publication_date = EXCLUDED.first_publication_date,
            publication_types = EXCLUDED.publication_types,
            mesh_headings = EXCLUDED.mesh_headings,
            chemicals = EXCLUDED.chemicals,
            cited_by_count = EXCLUDED.cited_by_count,
            is_open_access = EXCLUDED.is_open_access,
            in_europe_pmc = EXCLUDED.in_europe_pmc,
            source = EXCLUDED.source,
            source_version = EXCLUDED.source_version,
            source_url = EXCLUDED.source_url,
            raw_sha256 = EXCLUDED.raw_sha256,
            raw_payload = EXCLUDED.raw_payload,
            last_seen_at = NOW()
    """), values)
    session.execute(text("""
        INSERT INTO public_literature_record_history (
            article_source, external_id, response_sha256,
            source_version, raw_payload
        ) VALUES (
            :article_source, :external_id, :raw_sha,
            :source_version, CAST(:raw_payload AS JSONB)
        ) ON CONFLICT (
            article_source, external_id, response_sha256
        ) DO UPDATE SET last_fetched_at = NOW()
    """), values)
    return values


def _retain_page(
    *,
    candidate: dict[str, Any],
    payload: dict[str, Any],
    source_query: str,
) -> dict[str, Any]:
    source_version = str(payload.get("version") or "unknown")
    results = (payload.get("resultList") or {}).get("result") or []
    hit_count = int(payload.get("hitCount") or 0)
    next_cursor = payload.get("nextCursorMark")
    processed = int(candidate.get("processed_results") or 0) + len(results)
    complete = not next_cursor or processed >= hit_count
    query_hash = hashlib.sha256(source_query.encode()).hexdigest()
    raw_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    response_sha = hashlib.sha256(raw_json.encode()).hexdigest()
    with get_cortellis_session() as session:
        for result in results:
            values = _upsert_publication(
                session,
                result=result,
                source_version=source_version,
            )
            session.execute(text("""
                INSERT INTO public_target_literature_links (
                    ensembl_id, requested_accession, article_source,
                    external_id, match_method, source_query,
                    source, source_version
                ) VALUES (
                    :ensembl_id, :accession, :article_source,
                    :external_id, 'exact_structured_identifier_query',
                    :source_query, :source, :source_version
                ) ON CONFLICT (
                    ensembl_id, requested_accession,
                    article_source, external_id
                ) DO UPDATE SET
                    match_method = EXCLUDED.match_method,
                    source_query = EXCLUDED.source_query,
                    source = EXCLUDED.source,
                    source_version = EXCLUDED.source_version,
                    last_seen_at = NOW()
            """), {
                "ensembl_id": candidate["ensembl_id"],
                "accession": candidate["accession"],
                "article_source": values["article_source"],
                "external_id": values["external_id"],
                "source_query": source_query,
                "source": EUROPE_PMC_SOURCE,
                "source_version": source_version,
            })
        session.execute(text("""
            INSERT INTO europe_pmc_response_history (
                query_hash, cursor_mark, response_sha256,
                source_query, source_version, raw_payload
            ) VALUES (
                :query_hash, :cursor_mark, :response_sha,
                :source_query, :source_version, CAST(:raw_payload AS JSONB)
            ) ON CONFLICT (
                query_hash, cursor_mark, response_sha256
            ) DO UPDATE SET last_fetched_at = NOW()
        """), {
            "query_hash": query_hash,
            "cursor_mark": candidate["cursor_mark"],
            "response_sha": response_sha,
            "source_query": source_query,
            "source_version": source_version,
            "raw_payload": raw_json,
        })
        session.execute(text("""
            INSERT INTO public_target_literature_state (
                ensembl_id, requested_accession, source, source_query,
                query_hash, status, cursor_mark, hit_count,
                processed_results, pages_fetched, attempts,
                source_version, last_error, next_retry_at, next_refresh_at
            ) VALUES (
                :ensembl_id, :accession, :source, :source_query,
                :query_hash, :status, :next_cursor, :hit_count,
                :processed, :pages_fetched, 0,
                :source_version, NULL, NULL,
                CASE WHEN :status = 'complete'
                     THEN NOW() + INTERVAL '7 days' END
            ) ON CONFLICT (
                ensembl_id, requested_accession, source
            ) DO UPDATE SET
                source_query = EXCLUDED.source_query,
                query_hash = EXCLUDED.query_hash,
                status = EXCLUDED.status,
                cursor_mark = EXCLUDED.cursor_mark,
                hit_count = EXCLUDED.hit_count,
                processed_results = EXCLUDED.processed_results,
                pages_fetched = EXCLUDED.pages_fetched,
                attempts = 0,
                source_version = EXCLUDED.source_version,
                last_error = NULL,
                last_attempt_at = NOW(),
                next_retry_at = NULL,
                next_refresh_at = EXCLUDED.next_refresh_at
        """), {
            "ensembl_id": candidate["ensembl_id"],
            "accession": candidate["accession"],
            "source": EUROPE_PMC_SOURCE,
            "source_query": source_query,
            "query_hash": query_hash,
            "status": "complete" if complete else "in_progress",
            "next_cursor": None if complete else next_cursor,
            "hit_count": hit_count,
            "processed": processed,
            "pages_fetched": int(candidate.get("pages_fetched") or 0) + 1,
            "source_version": source_version,
        })
    return {
        "status": "completed",
        "target_status": "complete" if complete else "in_progress",
        "processed": len(results),
        "publications_upserted": len(results),
        "relationships_created": len(results),
        "hit_count": hit_count,
        "target_processed_results": processed,
        "source_version": source_version,
    }


def _record_failure(
    *,
    candidate: dict[str, Any],
    source_query: str,
    error: str,
) -> None:
    query_hash = hashlib.sha256(source_query.encode()).hexdigest()
    with get_cortellis_session() as session:
        session.execute(text("""
            INSERT INTO public_target_literature_state (
                ensembl_id, requested_accession, source, source_query,
                query_hash, status, cursor_mark, hit_count,
                processed_results, pages_fetched, attempts,
                last_error, next_retry_at
            ) VALUES (
                :ensembl_id, :accession, :source, :source_query,
                :query_hash, 'failed', :cursor_mark, :hit_count,
                :processed_results, :pages_fetched, 1,
                :error, NOW() + INTERVAL '30 minutes'
            ) ON CONFLICT (
                ensembl_id, requested_accession, source
            ) DO UPDATE SET
                status = 'failed',
                attempts = public_target_literature_state.attempts + 1,
                last_error = EXCLUDED.last_error,
                last_attempt_at = NOW(),
                next_retry_at = NOW() + INTERVAL '30 minutes'
                    * POWER(2, LEAST(public_target_literature_state.attempts, 4))
        """), {
            "ensembl_id": candidate["ensembl_id"],
            "accession": candidate["accession"],
            "source": EUROPE_PMC_SOURCE,
            "source_query": source_query,
            "query_hash": query_hash,
            "cursor_mark": candidate.get("cursor_mark") or "*",
            "hit_count": candidate.get("hit_count"),
            "processed_results": candidate.get("processed_results") or 0,
            "pages_fetched": candidate.get("pages_fetched") or 0,
            "error": error[:4000],
        })


def enrich_europe_pmc_target_literature(
    *,
    client: EuropePmcClient | None = None,
) -> dict[str, Any]:
    """Advance one exact target query by one durable cursor page."""
    ensure_europe_pmc_schema()
    lock = get_cortellis_engine().connect()
    acquired = bool(lock.execute(text(
        "SELECT pg_try_advisory_lock(hashtext('onebd_europe_pmc_enrichment'))"
    )).scalar())
    if not acquired:
        lock.close()
        return {
            "status": "skipped",
            "reason": "Europe PMC enrichment already running",
        }
    try:
        candidate = _candidate()
        if not candidate:
            return {
                "status": "completed",
                "processed": 0,
                "publications_upserted": 0,
                "relationships_created": 0,
            }
        source_query = exact_target_query(
            accession=candidate["accession"],
            ensembl_id=candidate["ensembl_id"],
        )
        try:
            payload = (client or EuropePmcClient()).target_publications(
                accession=candidate["accession"],
                ensembl_id=candidate["ensembl_id"],
                cursor_mark=candidate["cursor_mark"],
            )
        except Exception as exc:
            _record_failure(
                candidate=candidate,
                source_query=source_query,
                error=str(exc),
            )
            return {"status": "failed", "processed": 0, "error": str(exc)}
        return _retain_page(
            candidate=candidate,
            payload=payload,
            source_query=source_query,
        )
    finally:
        try:
            lock.execute(text(
                "SELECT pg_advisory_unlock(hashtext('onebd_europe_pmc_enrichment'))"
            ))
        finally:
            lock.close()


def europe_pmc_enrichment_status() -> dict[str, Any]:
    ensure_europe_pmc_schema()
    with get_cortellis_session() as session:
        row = session.execute(text("""
            SELECT
              (SELECT COUNT(*) FROM public_target_uniprot_records)
                  AS eligible_accessions,
              (SELECT COUNT(*) FROM public_literature_records) AS publications,
              (SELECT COUNT(*) FROM public_target_literature_links) AS links,
              (SELECT COUNT(DISTINCT ensembl_id)
               FROM public_target_literature_links) AS targets_with_publications,
              (SELECT COUNT(*) FROM public_target_literature_state
               WHERE source = :source AND status = 'complete')
                  AS completed_accessions,
              (SELECT MAX(source_version) FROM public_literature_records)
                  AS source_version
        """), {"source": EUROPE_PMC_SOURCE}).mappings().one()
        states = [dict(item) for item in session.execute(text("""
            SELECT status, COUNT(*) AS records,
                   SUM(processed_results) AS processed_results
            FROM public_target_literature_state
            WHERE source = :source
            GROUP BY status ORDER BY status
        """), {"source": EUROPE_PMC_SOURCE}).mappings().all()]
    result = dict(row)
    result["coverage_pct"] = round(
        100 * int(row["completed_accessions"] or 0)
        / max(1, int(row["eligible_accessions"] or 0)),
        2,
    )
    result["states"] = states
    return result
