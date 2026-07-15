"""Exact UniProtKB/Swiss-Prot enrichment for Open Targets target records."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import re
from typing import Any

from sqlalchemy import text

from unified_api.config import settings
from unified_api.services.database import (
    get_cortellis_engine,
    get_cortellis_session,
)
from unified_api.services.public_drug_enrichment import ensure_public_drug_schema
from unified_api.services.public_source_http import (
    PublicSourceHttpClient,
    RetryPolicy,
)


UNIPROT_SOURCE = "uniprot_rest"
UNIPROT_ACCESSION_PATTERN = (
    r"(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|"
    r"[A-NR-Z][0-9][A-Z][A-Z0-9]{2}[0-9]|"
    r"[A-NR-Z][0-9][A-Z0-9]{3}[0-9][A-Z0-9]{3}[0-9])"
)
_uniprot_accession = re.compile(rf"{UNIPROT_ACCESSION_PATTERN}\Z")
_public_target_schema_ready = False


class UniProtClient:
    """Batched adapter for exact accessions in the official UniProt REST API."""

    def __init__(self, *, base_url: str | None = None):
        self._http = PublicSourceHttpClient(
            source=UNIPROT_SOURCE,
            base_url=base_url or settings.uniprot_base_url,
            user_agent=settings.public_data_user_agent,
            timeout=60,
            min_interval_seconds=settings.uniprot_request_interval_seconds,
            retry_policy=RetryPolicy(max_retries=3),
        )

    def entries(
        self,
        accessions: list[str],
    ) -> tuple[dict[str, dict[str, Any]], dict[str, str | None]]:
        """Return entries keyed only by an exact primary or secondary accession."""
        normalized = list(dict.fromkeys(value.upper() for value in accessions))
        if not normalized:
            return {}, {"release": None, "release_date": None}
        for accession in normalized:
            if not _uniprot_accession.fullmatch(accession):
                raise ValueError(f"Invalid UniProt accession: {accession}")

        response = self._http.get_json("/uniprotkb/search", {
            "query": "(" + " OR ".join(
                f"accession:{accession}" for accession in normalized
            ) + ")",
            "format": "json",
            "size": len(normalized),
        })
        if response is None:
            raise RuntimeError("UniProt response was empty")
        results = response.payload.get("results")
        if not isinstance(results, list):
            raise ValueError("UniProt returned a non-list results payload")
        headers = response.response_headers or {}
        total_text = headers.get("x-total-results")
        if total_text is not None and int(total_text) > len(results):
            raise ValueError("UniProt exact accession response was truncated")

        requested = set(normalized)
        by_accession: dict[str, dict[str, Any]] = {}
        for entry in results:
            identities = {
                str(entry.get("primaryAccession") or "").upper(),
                *(
                    str(value).upper()
                    for value in entry.get("secondaryAccessions") or []
                ),
            }
            for accession in requested.intersection(identities):
                if accession in by_accession:
                    raise ValueError(
                        f"UniProt returned multiple entries for {accession}"
                    )
                by_accession[accession] = entry
        return by_accession, {
            "release": headers.get("x-uniprot-release"),
            "release_date": headers.get("x-uniprot-release-date"),
        }


def _iso_release_date(value: str | None) -> str | None:
    if not value:
        return None
    for pattern in ("%d-%B-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"Unrecognized UniProt release date: {value}")


def ensure_public_target_schema() -> None:
    """Create target-source state plus current and immutable UniProt records."""
    global _public_target_schema_ready
    if _public_target_schema_ready:
        return
    from unified_api.services.runtime_schema import runtime_schema_is_pre_migrated

    if runtime_schema_is_pre_migrated():
        _public_target_schema_ready = True
        return
    ensure_public_drug_schema()
    with get_cortellis_session() as session:
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS public_target_source_state (
                ensembl_id VARCHAR(30) NOT NULL
                    REFERENCES public_targets(ensembl_id) ON DELETE CASCADE,
                source VARCHAR(100) NOT NULL,
                source_identifier VARCHAR(100) NOT NULL,
                status VARCHAR(20) NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                source_version VARCHAR(50),
                last_error TEXT,
                last_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                next_retry_at TIMESTAMPTZ,
                PRIMARY KEY (ensembl_id, source, source_identifier)
            )
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_public_target_source_state_queue
            ON public_target_source_state (
                source, source_version, status, next_retry_at, ensembl_id
            )
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS public_target_uniprot_records (
                ensembl_id VARCHAR(30) NOT NULL
                    REFERENCES public_targets(ensembl_id) ON DELETE CASCADE,
                requested_accession VARCHAR(20) NOT NULL,
                primary_accession VARCHAR(20) NOT NULL,
                uniprot_id VARCHAR(100),
                entry_type VARCHAR(100) NOT NULL,
                reviewed BOOLEAN NOT NULL,
                protein_name TEXT,
                gene_symbol VARCHAR(100),
                gene_synonyms JSONB NOT NULL DEFAULT '[]'::jsonb,
                organism_name TEXT,
                organism_taxon_id INTEGER,
                function_text TEXT,
                disease_annotations JSONB NOT NULL DEFAULT '[]'::jsonb,
                subcellular_locations JSONB NOT NULL DEFAULT '[]'::jsonb,
                sequence_length INTEGER,
                sequence_checksum VARCHAR(100),
                source VARCHAR(100) NOT NULL,
                source_version VARCHAR(50) NOT NULL,
                source_release_date DATE,
                source_url TEXT NOT NULL,
                raw_sha256 CHAR(64) NOT NULL,
                raw_payload JSONB NOT NULL,
                first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (ensembl_id, requested_accession)
            )
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_public_target_uniprot_primary
            ON public_target_uniprot_records (primary_accession)
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS public_target_uniprot_history (
                ensembl_id VARCHAR(30) NOT NULL
                    REFERENCES public_targets(ensembl_id) ON DELETE CASCADE,
                requested_accession VARCHAR(20) NOT NULL,
                primary_accession VARCHAR(20) NOT NULL,
                response_sha256 CHAR(64) NOT NULL,
                source_version VARCHAR(50) NOT NULL,
                raw_payload JSONB NOT NULL,
                first_fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (
                    ensembl_id, requested_accession, response_sha256
                )
            )
        """))
    _public_target_schema_ready = True


def _target_candidates(source_version: str, batch_size: int) -> list[dict[str, Any]]:
    with get_cortellis_session() as session:
        return [dict(row) for row in session.execute(text("""
            SELECT DISTINCT target.ensembl_id,
                   UPPER(protein.item->>'id') AS accession
            FROM public_targets target
            CROSS JOIN LATERAL jsonb_array_elements(target.protein_ids)
                AS protein(item)
            LEFT JOIN public_target_source_state state
              ON state.ensembl_id = target.ensembl_id
             AND state.source = :source
             AND state.source_identifier = UPPER(protein.item->>'id')
            WHERE LOWER(protein.item->>'source') = 'uniprot_swissprot'
              AND UPPER(protein.item->>'id') ~ :accession_pattern
              AND (
                state.ensembl_id IS NULL OR
                state.source_version IS DISTINCT FROM :source_version OR
                (state.status = 'failed' AND state.attempts < 3
                 AND state.next_retry_at <= NOW())
              )
            ORDER BY target.ensembl_id, accession
            LIMIT :batch_size
        """), {
            "source": UNIPROT_SOURCE,
            "source_version": source_version,
            "accession_pattern": f"^{UNIPROT_ACCESSION_PATTERN}$",
            "batch_size": batch_size,
        }).mappings().all()]


def _record_target_state(
    session,
    *,
    ensembl_id: str,
    accession: str,
    status: str,
    source_version: str,
    error: str | None = None,
) -> None:
    session.execute(text("""
        INSERT INTO public_target_source_state (
            ensembl_id, source, source_identifier, status, attempts,
            source_version, last_error, next_retry_at
        ) VALUES (
            :ensembl_id, :source, :accession, :status, 1,
            :source_version, :error,
            CASE WHEN :status = 'failed'
                 THEN NOW() + INTERVAL '30 minutes' END
        ) ON CONFLICT (ensembl_id, source, source_identifier) DO UPDATE SET
            status = EXCLUDED.status,
            attempts = CASE
                WHEN public_target_source_state.source_version
                     IS DISTINCT FROM EXCLUDED.source_version THEN 1
                ELSE public_target_source_state.attempts + 1
            END,
            source_version = EXCLUDED.source_version,
            last_error = EXCLUDED.last_error,
            last_attempt_at = NOW(),
            next_retry_at = EXCLUDED.next_retry_at
    """), {
        "ensembl_id": ensembl_id,
        "source": UNIPROT_SOURCE,
        "accession": accession,
        "status": status,
        "source_version": source_version,
        "error": error[:4000] if error else None,
    })


def _protein_name(entry: dict[str, Any]) -> str | None:
    description = entry.get("proteinDescription") or {}
    candidates = [
        (description.get("recommendedName") or {}).get("fullName"),
        *((item.get("fullName") for item in description.get("submissionNames") or [])),
    ]
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate.get("value"):
            return str(candidate["value"])
    return None


def _gene_details(entry: dict[str, Any]) -> tuple[str | None, list[str]]:
    genes = entry.get("genes") or []
    if not genes:
        return None, []
    first = genes[0]
    symbol = (first.get("geneName") or {}).get("value")
    synonyms = [
        str(item["value"])
        for gene in genes
        for item in gene.get("synonyms") or []
        if item.get("value")
    ]
    return str(symbol) if symbol else None, list(dict.fromkeys(synonyms))


def _comments(entry: dict[str, Any], comment_type: str) -> list[dict[str, Any]]:
    return [
        comment for comment in entry.get("comments") or []
        if comment.get("commentType") == comment_type
    ]


def _function_text(entry: dict[str, Any]) -> str | None:
    values = [
        str(item["value"])
        for comment in _comments(entry, "FUNCTION")
        for item in comment.get("texts") or []
        if item.get("value")
    ]
    return "\n".join(values) or None


def _upsert_uniprot_record(
    session,
    *,
    ensembl_id: str,
    requested_accession: str,
    entry: dict[str, Any],
    source_version: str,
    source_release_date: str | None,
) -> None:
    primary_accession = str(entry["primaryAccession"]).upper()
    entry_type = str(entry.get("entryType") or "")
    reviewed = "reviewed (Swiss-Prot)" in entry_type
    gene_symbol, gene_synonyms = _gene_details(entry)
    organism = entry.get("organism") or {}
    sequence = entry.get("sequence") or {}
    raw_json = json.dumps(entry, sort_keys=True, separators=(",", ":"))
    raw_sha = hashlib.sha256(raw_json.encode()).hexdigest()
    source_url = f"https://www.uniprot.org/uniprotkb/{primary_accession}/entry"
    values = {
        "ensembl_id": ensembl_id,
        "requested_accession": requested_accession,
        "primary_accession": primary_accession,
        "uniprot_id": entry.get("uniProtkbId"),
        "entry_type": entry_type,
        "reviewed": reviewed,
        "protein_name": _protein_name(entry),
        "gene_symbol": gene_symbol,
        "gene_synonyms": json.dumps(gene_synonyms),
        "organism_name": organism.get("scientificName"),
        "organism_taxon_id": organism.get("taxonId"),
        "function_text": _function_text(entry),
        "disease_annotations": json.dumps(_comments(entry, "DISEASE")),
        "subcellular_locations": json.dumps(
            _comments(entry, "SUBCELLULAR LOCATION")
        ),
        "sequence_length": sequence.get("length"),
        "sequence_checksum": sequence.get("crc64"),
        "source": UNIPROT_SOURCE,
        "source_version": source_version,
        "source_release_date": source_release_date,
        "source_url": source_url,
        "raw_sha": raw_sha,
        "raw_payload": raw_json,
    }
    session.execute(text("""
        INSERT INTO public_target_uniprot_records (
            ensembl_id, requested_accession, primary_accession, uniprot_id,
            entry_type, reviewed, protein_name, gene_symbol, gene_synonyms,
            organism_name, organism_taxon_id, function_text,
            disease_annotations, subcellular_locations, sequence_length,
            sequence_checksum, source, source_version, source_release_date,
            source_url, raw_sha256, raw_payload
        ) VALUES (
            :ensembl_id, :requested_accession, :primary_accession, :uniprot_id,
            :entry_type, :reviewed, :protein_name, :gene_symbol,
            CAST(:gene_synonyms AS JSONB), :organism_name, :organism_taxon_id,
            :function_text, CAST(:disease_annotations AS JSONB),
            CAST(:subcellular_locations AS JSONB), :sequence_length,
            :sequence_checksum, :source, :source_version,
            :source_release_date, :source_url, :raw_sha,
            CAST(:raw_payload AS JSONB)
        ) ON CONFLICT (ensembl_id, requested_accession) DO UPDATE SET
            primary_accession = EXCLUDED.primary_accession,
            uniprot_id = EXCLUDED.uniprot_id,
            entry_type = EXCLUDED.entry_type,
            reviewed = EXCLUDED.reviewed,
            protein_name = EXCLUDED.protein_name,
            gene_symbol = EXCLUDED.gene_symbol,
            gene_synonyms = EXCLUDED.gene_synonyms,
            organism_name = EXCLUDED.organism_name,
            organism_taxon_id = EXCLUDED.organism_taxon_id,
            function_text = EXCLUDED.function_text,
            disease_annotations = EXCLUDED.disease_annotations,
            subcellular_locations = EXCLUDED.subcellular_locations,
            sequence_length = EXCLUDED.sequence_length,
            sequence_checksum = EXCLUDED.sequence_checksum,
            source = EXCLUDED.source,
            source_version = EXCLUDED.source_version,
            source_release_date = EXCLUDED.source_release_date,
            source_url = EXCLUDED.source_url,
            raw_sha256 = EXCLUDED.raw_sha256,
            raw_payload = EXCLUDED.raw_payload,
            last_seen_at = NOW()
    """), values)
    session.execute(text("""
        INSERT INTO public_target_uniprot_history (
            ensembl_id, requested_accession, primary_accession,
            response_sha256, source_version, raw_payload
        ) VALUES (
            :ensembl_id, :requested_accession, :primary_accession,
            :raw_sha, :source_version, CAST(:raw_payload AS JSONB)
        ) ON CONFLICT (
            ensembl_id, requested_accession, response_sha256
        ) DO UPDATE SET last_fetched_at = NOW()
    """), values)


def enrich_uniprot_targets(
    *,
    batch_size: int = 50,
    client: UniProtClient | None = None,
) -> dict[str, Any]:
    """Retain reviewed UniProt records linked by exact Open Targets accessions."""
    ensure_public_target_schema()
    lock = get_cortellis_engine().connect()
    acquired = bool(lock.execute(text(
        "SELECT pg_try_advisory_lock(hashtext('onebd_uniprot_enrichment'))"
    )).scalar())
    if not acquired:
        lock.close()
        return {"status": "skipped", "reason": "UniProt enrichment already running"}
    try:
        client = client or UniProtClient()
        # A one-entry exact request supplies the current release before selection,
        # so completed accessions are rechecked only when UniProt changes release.
        seed_entries, seed_metadata = client.entries(["P29274"])
        if "P29274" not in seed_entries:
            raise RuntimeError("UniProt release probe did not return P29274")
        source_version = str(seed_metadata.get("release") or "")
        if not source_version:
            raise RuntimeError("UniProt response omitted x-uniprot-release")
        release_date = _iso_release_date(seed_metadata.get("release_date"))
        candidates = _target_candidates(source_version, batch_size)
        if not candidates:
            return {
                "status": "completed",
                "processed": 0,
                "matched": 0,
                "not_found": 0,
                "failed": 0,
                "source_version": source_version,
                "source_data_at": release_date,
            }
        accessions = list(dict.fromkeys(
            candidate["accession"] for candidate in candidates
        ))
        entries, metadata = client.entries(accessions)
        response_version = str(metadata.get("release") or "")
        if response_version != source_version:
            raise ValueError("UniProt release changed during the enrichment batch")
        response_release_date = _iso_release_date(metadata.get("release_date"))
        if response_release_date != release_date:
            raise ValueError("UniProt release date changed during the enrichment batch")

        matched = 0
        not_found = 0
        failed = 0
        with get_cortellis_session() as session:
            for candidate in candidates:
                entry = entries.get(candidate["accession"])
                if entry is None:
                    not_found += 1
                    _record_target_state(
                        session,
                        ensembl_id=candidate["ensembl_id"],
                        accession=candidate["accession"],
                        status="not_found",
                        source_version=source_version,
                    )
                    continue
                entry_type = str(entry.get("entryType") or "")
                if "reviewed (Swiss-Prot)" not in entry_type:
                    failed += 1
                    _record_target_state(
                        session,
                        ensembl_id=candidate["ensembl_id"],
                        accession=candidate["accession"],
                        status="failed",
                        source_version=source_version,
                        error="Open Targets Swiss-Prot ID returned an unreviewed entry",
                    )
                    continue
                _upsert_uniprot_record(
                    session,
                    ensembl_id=candidate["ensembl_id"],
                    requested_accession=candidate["accession"],
                    entry=entry,
                    source_version=source_version,
                    source_release_date=release_date,
                )
                matched += 1
                _record_target_state(
                    session,
                    ensembl_id=candidate["ensembl_id"],
                    accession=candidate["accession"],
                    status="matched",
                    source_version=source_version,
                )
        return {
            "status": "partial" if failed else "completed",
            "processed": len(candidates),
            "matched": matched,
            "not_found": not_found,
            "failed": failed,
            "source_version": source_version,
            "source_data_at": release_date,
        }
    finally:
        try:
            lock.execute(text(
                "SELECT pg_advisory_unlock(hashtext('onebd_uniprot_enrichment'))"
            ))
        finally:
            lock.close()


def uniprot_enrichment_status() -> dict[str, Any]:
    ensure_public_target_schema()
    with get_cortellis_session() as session:
        row = session.execute(text("""
            SELECT
              (SELECT COUNT(DISTINCT (target.ensembl_id, protein.item->>'id'))
               FROM public_targets target
               CROSS JOIN LATERAL jsonb_array_elements(target.protein_ids)
                   AS protein(item)
               WHERE LOWER(protein.item->>'source') = 'uniprot_swissprot')
                  AS eligible_accessions,
              (SELECT COUNT(*) FROM public_target_uniprot_records) AS records,
              (SELECT COUNT(DISTINCT ensembl_id)
               FROM public_target_uniprot_records) AS targets_with_records,
              (SELECT MAX(source_version)
               FROM public_target_uniprot_records) AS source_version,
              (SELECT MAX(source_release_date)
               FROM public_target_uniprot_records) AS source_release_date
        """)).mappings().one()
        states = [dict(item) for item in session.execute(text("""
            SELECT status, COUNT(*) AS records
            FROM public_target_source_state
            WHERE source = :source
            GROUP BY status ORDER BY status
        """), {"source": UNIPROT_SOURCE}).mappings().all()]
    result = dict(row)
    result["coverage_pct"] = round(
        100 * int(row["records"] or 0)
        / max(1, int(row["eligible_accessions"] or 0)),
        2,
    )
    result["states"] = states
    return result
