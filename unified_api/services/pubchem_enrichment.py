"""Conservative, resumable public identifier enrichment from PubChem PUG REST."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import time
from urllib.parse import quote
from urllib.request import urlopen

from sqlalchemy import text

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


PUBCHEM_BASE_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
_pubchem_schema_ready = False

# A development code can be reused across organizations and modalities. PubChem
# exact-name lookup alone is therefore not enough to map a macromolecular
# program to a small-molecule record carrying the same code.
_MACRO_BIOLOGIC_TECHNOLOGY_TERMS = (
    "antibody",
    "bispecific",
    "multispecific",
    "t-cell engager",
    "t cell engager",
    "cell therapy",
    "gene therapy",
    "viral vector",
    "oncolytic virus",
    "fusion protein",
    "protein fusion",
)


@dataclass(frozen=True)
class PubChemMatch:
    cid: int
    title: str
    inchikey: str | None
    connectivity_smiles: str | None


def _is_code_like(value: str | None, alias_type: str | None = None) -> bool:
    if alias_type == "development_code":
        return True
    compact = (value or "").strip()
    return bool(re.fullmatch(
        r"[A-Za-z]{1,10}(?:[- /]?[A-Za-z]{0,5})?[- /]?\d{2,}(?:[- /]\d+)?",
        compact,
    ))


def pubchem_match_context_supported(
    *,
    query_name: str,
    pubchem_title: str,
    alias_type: str | None = None,
    technologies: list[str] | tuple[str, ...] = (),
    corroborating_aliases: list[str] | tuple[str, ...] = (),
) -> tuple[bool, str]:
    """Reject uncorroborated code collisions for clear macro-biologic assets."""
    normalized_technologies = " | ".join(technologies).casefold()
    macro_biologic = any(
        term in normalized_technologies
        for term in _MACRO_BIOLOGIC_TECHNOLOGY_TERMS
    )
    if not macro_biologic:
        return True, "no_macro_biologic_conflict"
    if not _is_code_like(query_name, alias_type):
        return True, "query_is_not_a_development_code"
    if (
        _normalized_name(query_name) == _normalized_name(pubchem_title)
        or bool(_name_tokens(query_name) & _name_tokens(pubchem_title))
    ):
        return True, "pubchem_title_matches_query"
    for alias in corroborating_aliases:
        if (
            _normalized_name(alias) == _normalized_name(pubchem_title)
            or bool(_name_tokens(alias) & _name_tokens(pubchem_title))
        ):
            return True, "pubchem_title_corroborated_by_source_alias"
    return False, "uncorroborated_macro_biologic_development_code"


class PubChemClient:
    def __init__(
        self,
        *,
        timeout: float = 20,
        delay_seconds: float = 0.22,
        max_retries: int = 2,
    ):
        self.timeout = timeout
        self.delay_seconds = delay_seconds
        self.max_retries = max_retries
        self._http = PublicSourceHttpClient(
            source="pubchem_pug_rest",
            base_url=PUBCHEM_BASE_URL,
            user_agent="OneBD/1.0 admin@pchomelab.com",
            timeout=timeout,
            min_interval_seconds=delay_seconds,
            retry_policy=RetryPolicy(
                max_retries=max_retries,
                retry_statuses=frozenset({429, 503}),
                backoff_seconds=max(delay_seconds, 1.0),
            ),
            opener=urlopen,
            sleep=time.sleep,
        )

    def lookup_name(self, name: str) -> PubChemMatch | None:
        encoded = quote(name, safe="")
        path = (
            f"/compound/name/{encoded}/property/"
            "Title,InChIKey,ConnectivitySMILES/JSON"
        )
        response = self._http.get_json(path, not_found_is_none=True)
        if response is None:
            return None
        payload = response.payload
        properties = payload.get("PropertyTable", {}).get("Properties", [])
        if len(properties) != 1:
            return None
        item = properties[0]
        return PubChemMatch(
            cid=int(item["CID"]),
            title=str(item.get("Title") or name),
            inchikey=item.get("InChIKey"),
            connectivity_smiles=item.get("ConnectivitySMILES"),
        )


def ensure_pubchem_schema() -> None:
    global _pubchem_schema_ready
    if _pubchem_schema_ready:
        return
    EntityResolutionService().ensure_identity_schema()
    with get_cortellis_session() as session:
        # A public compound can legitimately map to more than one Cortellis
        # formulation/asset row, so uniqueness belongs to the association.
        session.execute(text("""
            ALTER TABLE drug_identifiers
            DROP CONSTRAINT IF EXISTS drug_identifiers_identifier_type_normalized_value_key
        """))
        session.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_drug_identifier_identity
            ON drug_identifiers (drug_id, identifier_type, normalized_value)
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS drug_public_enrichment_state (
                drug_id INTEGER NOT NULL REFERENCES drugs(id) ON DELETE CASCADE,
                source VARCHAR(50) NOT NULL,
                query_name VARCHAR(1000) NOT NULL,
                status VARCHAR(20) NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                matched_identifier VARCHAR(500),
                last_error TEXT,
                last_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                next_retry_at TIMESTAMPTZ,
                PRIMARY KEY (drug_id, source)
            )
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS drug_public_enrichment_queries (
                drug_id INTEGER NOT NULL REFERENCES drugs(id) ON DELETE CASCADE,
                source VARCHAR(50) NOT NULL,
                normalized_query VARCHAR(1000) NOT NULL,
                query_name VARCHAR(1000) NOT NULL,
                status VARCHAR(20) NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                matched_identifier VARCHAR(500),
                last_error TEXT,
                last_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                next_retry_at TIMESTAMPTZ,
                PRIMARY KEY (drug_id, source, normalized_query)
            )
        """))
        # Carry forward the one-query-per-drug history so an old not-found
        # result advances to a genuinely different alias instead of repeating.
        session.execute(text("""
            INSERT INTO drug_public_enrichment_queries (
                drug_id, source, normalized_query, query_name, status, attempts,
                matched_identifier, last_error, last_attempt_at, next_retry_at
            )
            SELECT drug_id, source,
                   LOWER(REGEXP_REPLACE(TRIM(query_name), '\\s+', ' ', 'g')),
                   query_name, status, attempts, matched_identifier, last_error,
                   last_attempt_at, next_retry_at
            FROM drug_public_enrichment_state
            WHERE source = 'pubchem'
            ON CONFLICT DO NOTHING
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_drug_public_queries_status
            ON drug_public_enrichment_queries (
                source, status, next_retry_at, drug_id
            )
        """))
    _pubchem_schema_ready = True


def _candidates(batch_size: int) -> list[dict]:
    with get_cortellis_session() as session:
        return [dict(row) for row in session.execute(text("""
            SELECT candidates.drug_id,
                   candidates.alias_value AS query_name,
                   candidates.normalized_value,
                   candidates.alias_type,
                   ARRAY(
                       SELECT DISTINCT technology.name::text
                       FROM deal_drugs drug_deal
                       JOIN deal_technologies deal_technology
                         ON deal_technology.deal_id = drug_deal.deal_id
                       JOIN technologies technology
                         ON technology.id = deal_technology.technology_id
                       WHERE drug_deal.drug_id = candidates.drug_id
                       ORDER BY technology.name::text
                   ) AS technologies,
                   ARRAY(
                       SELECT DISTINCT corroborating.alias_value::text
                       FROM drug_aliases corroborating
                       WHERE corroborating.drug_id = candidates.drug_id
                         AND corroborating.source <> 'pubchem'
                         AND corroborating.normalized_value
                             <> candidates.normalized_value
                       ORDER BY corroborating.alias_value::text
                   ) AS corroborating_aliases
            FROM (
                SELECT da.drug_id, da.alias_type, da.alias_value,
                       da.normalized_value,
                       ROW_NUMBER() OVER (
                           PARTITION BY da.drug_id
                           ORDER BY CASE da.alias_type
                               WHEN 'primary_name_candidate' THEN 1
                               WHEN 'development_code' THEN 2
                               ELSE 3 END,
                               LENGTH(da.alias_value)
                       ) AS position
                FROM drug_aliases da
                LEFT JOIN drug_public_enrichment_state summary
                  ON summary.drug_id = da.drug_id
                 AND summary.source = 'pubchem'
                LEFT JOIN drug_public_enrichment_queries query_state
                  ON query_state.drug_id = da.drug_id
                 AND query_state.source = 'pubchem'
                 AND query_state.normalized_query = da.normalized_value
                WHERE da.alias_type IN (
                    'primary_name_candidate', 'development_code', 'display_name'
                )
                  AND COALESCE(summary.status, '') <> 'matched'
                  AND NOT EXISTS (
                    SELECT 1
                    FROM drug_public_enrichment_queries matched_query
                    WHERE matched_query.drug_id = da.drug_id
                      AND matched_query.source = 'pubchem'
                      AND matched_query.status = 'matched'
                  )
                  AND (
                    query_state.drug_id IS NULL OR
                    (query_state.status = 'failed'
                     AND query_state.attempts < 3
                     AND query_state.next_retry_at <= NOW())
                  )
            ) candidates
            WHERE candidates.position = 1
            ORDER BY candidates.drug_id
            LIMIT :batch_size
        """), {"batch_size": batch_size}).mappings().all()]


def enrich_pubchem_batch(
    *, batch_size: int = 100, client: PubChemClient | None = None
) -> dict:
    """Run one globally serialized, policy-rate-limited enrichment batch."""
    ensure_pubchem_schema()
    lock_connection = get_cortellis_engine().connect()
    acquired = bool(lock_connection.execute(text(
        "SELECT pg_try_advisory_lock(hashtext('onebd_pubchem_enrichment'))"
    )).scalar())
    if not acquired:
        lock_connection.close()
        return {
            "status": "busy",
            "reason": "PubChem enrichment already running",
            "processed": 0,
            "matched": 0,
            "not_found": 0,
            "context_conflicts": 0,
            "failed": 0,
        }

    try:
        return _enrich_pubchem_candidates(batch_size=batch_size, client=client)
    finally:
        try:
            lock_connection.execute(text(
                "SELECT pg_advisory_unlock(hashtext('onebd_pubchem_enrichment'))"
            ))
        finally:
            lock_connection.close()


def _enrich_pubchem_candidates(
    *, batch_size: int, client: PubChemClient | None
) -> dict:
    """Process candidates while the caller holds the global batch lock."""
    client = client or PubChemClient()
    candidates = _candidates(batch_size)
    matched = 0
    not_found = 0
    context_conflicts = 0
    failed = 0
    for candidate in candidates:
        drug_id = candidate["drug_id"]
        query_name = candidate["query_name"]
        normalized_query = candidate.get("normalized_value") or normalize_identifier_value(
            "drug_alias",
            query_name,
        )
        try:
            match = client.lookup_name(query_name)
            if match is None:
                not_found += 1
                with get_cortellis_session() as session:
                    _record_query_state(
                        session,
                        drug_id,
                        query_name,
                        normalized_query,
                        "not_found",
                    )
                    _refresh_summary_state(session, drug_id, query_name)
                continue
            context_supported, context_reason = pubchem_match_context_supported(
                query_name=query_name,
                pubchem_title=match.title,
                alias_type=candidate.get("alias_type"),
                technologies=candidate.get("technologies") or (),
                corroborating_aliases=(
                    candidate.get("corroborating_aliases") or ()
                ),
            )
            if not context_supported:
                context_conflicts += 1
                error = json.dumps({
                    "reason": context_reason,
                    "pubchem_cid": match.cid,
                    "pubchem_title": match.title,
                    "technologies": candidate.get("technologies") or [],
                })
                with get_cortellis_session() as session:
                    _record_query_state(
                        session,
                        drug_id,
                        query_name,
                        normalized_query,
                        "context_conflict",
                        error=error,
                    )
                    _refresh_summary_state(
                        session,
                        drug_id,
                        query_name,
                        error=error,
                    )
                continue
            evidence = json.dumps({
                "query_name": query_name,
                "pubchem_title": match.title,
                "pubchem_cid": match.cid,
            })
            identifiers = [
                ("pubchem_cid", str(match.cid)),
                ("inchikey", match.inchikey),
                ("connectivity_smiles", match.connectivity_smiles),
            ]
            with get_cortellis_session() as session:
                for identifier_type, value in identifiers:
                    if not value or len(value) > 500:
                        continue
                    session.execute(text("""
                        INSERT INTO drug_identifiers (
                            drug_id, identifier_type, identifier_value,
                            normalized_value, source, source_reference,
                            evidence, confidence, review_status
                        ) VALUES (
                            :drug_id, :identifier_type, :value, :value,
                            'pubchem', :source_reference, CAST(:evidence AS JSONB),
                            0.95, 'source_verified'
                        ) ON CONFLICT DO NOTHING
                    """), {
                        "drug_id": drug_id,
                        "identifier_type": identifier_type,
                        "value": value,
                        "source_reference": f"https://pubchem.ncbi.nlm.nih.gov/compound/{match.cid}",
                        "evidence": evidence,
                    })
                session.execute(text("""
                    INSERT INTO drug_aliases (
                        drug_id, alias_type, alias_value, normalized_value,
                        source, source_reference, evidence, confidence, review_status
                    ) VALUES (
                        :drug_id, 'pubchem_title', :title, LOWER(:title),
                        'pubchem', :source_reference, CAST(:evidence AS JSONB),
                        0.95, 'source_verified'
                    ) ON CONFLICT DO NOTHING
                """), {
                    "drug_id": drug_id,
                    "title": match.title,
                    "source_reference": f"https://pubchem.ncbi.nlm.nih.gov/compound/{match.cid}",
                    "evidence": evidence,
                })
                _record_state(
                    session, drug_id, query_name, "matched",
                    matched_identifier=str(match.cid),
                )
                _record_query_state(
                    session,
                    drug_id,
                    query_name,
                    normalized_query,
                    "matched",
                    matched_identifier=str(match.cid),
                )
            matched += 1
        except Exception as exc:
            failed += 1
            with get_cortellis_session() as session:
                error = str(exc)[:2000]
                _record_query_state(
                    session,
                    drug_id,
                    query_name,
                    normalized_query,
                    "failed",
                    error=error,
                )
                _refresh_summary_state(session, drug_id, query_name, error=error)
    return {
        "status": "completed" if failed == 0 else "partial",
        "processed": len(candidates),
        "matched": matched,
        "not_found": not_found,
        "context_conflicts": context_conflicts,
        "failed": failed,
    }


def _record_query_state(
    session,
    drug_id: int,
    query_name: str,
    normalized_query: str,
    status: str,
    *,
    matched_identifier: str | None = None,
    error: str | None = None,
) -> None:
    session.execute(text("""
        INSERT INTO drug_public_enrichment_queries (
            drug_id, source, normalized_query, query_name, status, attempts,
            matched_identifier, last_error, last_attempt_at, next_retry_at
        ) VALUES (
            :drug_id, 'pubchem', :normalized_query, :query_name, :status, 1,
            :matched_identifier, :error, NOW(),
            CASE WHEN :status = 'failed' THEN NOW() + INTERVAL '1 hour' END
        ) ON CONFLICT (drug_id, source, normalized_query) DO UPDATE SET
            query_name = EXCLUDED.query_name,
            status = EXCLUDED.status,
            attempts = drug_public_enrichment_queries.attempts + 1,
            matched_identifier = EXCLUDED.matched_identifier,
            last_error = EXCLUDED.last_error,
            last_attempt_at = NOW(),
            next_retry_at = CASE WHEN EXCLUDED.status = 'failed'
                THEN NOW() + INTERVAL '1 hour' *
                    POWER(2, LEAST(drug_public_enrichment_queries.attempts, 5))
                END
    """), {
        "drug_id": drug_id,
        "normalized_query": normalized_query,
        "query_name": query_name,
        "status": status,
        "matched_identifier": matched_identifier,
        "error": error,
    })


def _refresh_summary_state(
    session,
    drug_id: int,
    query_name: str,
    *,
    error: str | None = None,
) -> None:
    """Roll per-alias attempts into an honest per-drug operational state."""
    counts = session.execute(text("""
        SELECT
            COUNT(*) FILTER (WHERE query_state.drug_id IS NULL) AS untried,
            COUNT(*) FILTER (
                WHERE query_state.status = 'failed'
                  AND query_state.attempts < 3
            ) AS retryable_failed,
            COUNT(*) FILTER (
                WHERE query_state.status = 'failed'
                  AND query_state.attempts >= 3
            ) AS terminal_failed,
            COUNT(*) FILTER (WHERE query_state.status = 'matched') AS matched,
            COUNT(*) FILTER (
                WHERE query_state.status = 'context_conflict'
            ) AS context_conflicts
        FROM drug_aliases da
        LEFT JOIN drug_public_enrichment_queries query_state
          ON query_state.drug_id = da.drug_id
         AND query_state.source = 'pubchem'
         AND query_state.normalized_query = da.normalized_value
        WHERE da.drug_id = :drug_id
          AND da.alias_type IN (
              'primary_name_candidate', 'development_code', 'display_name'
          )
    """), {"drug_id": drug_id}).mappings().one()

    if counts["matched"]:
        return
    if counts["untried"]:
        status = "pending"
    elif counts["retryable_failed"] or counts["terminal_failed"]:
        status = "failed"
    elif counts["context_conflicts"]:
        status = "context_conflict"
    else:
        status = "not_found"
    _record_state(
        session,
        drug_id,
        query_name,
        status,
        error=error if status in {"failed", "context_conflict"} else None,
    )


def _record_state(
    session,
    drug_id: int,
    query_name: str,
    status: str,
    *,
    matched_identifier: str | None = None,
    error: str | None = None,
) -> None:
    session.execute(text("""
        INSERT INTO drug_public_enrichment_state (
            drug_id, source, query_name, status, attempts,
            matched_identifier, last_error, last_attempt_at, next_retry_at
        ) VALUES (
            :drug_id, 'pubchem', :query_name, :status, 1,
            :matched_identifier, :error, NOW(),
            CASE WHEN :status = 'failed' THEN NOW() + INTERVAL '1 hour' END
        ) ON CONFLICT (drug_id, source) DO UPDATE SET
            query_name = EXCLUDED.query_name,
            status = EXCLUDED.status,
            attempts = drug_public_enrichment_state.attempts + 1,
            matched_identifier = EXCLUDED.matched_identifier,
            last_error = EXCLUDED.last_error,
            last_attempt_at = NOW(),
            next_retry_at = CASE WHEN EXCLUDED.status = 'failed'
                THEN NOW() + INTERVAL '1 hour' *
                    POWER(2, LEAST(drug_public_enrichment_state.attempts, 5))
                END
    """), {
        "drug_id": drug_id,
        "query_name": query_name,
        "status": status,
        "matched_identifier": matched_identifier,
        "error": error,
    })


def pubchem_enrichment_status() -> dict:
    """Return per-drug, per-query, and identifier coverage."""
    ensure_pubchem_schema()
    with get_cortellis_session() as session:
        row = session.execute(text("""
            WITH per_drug AS (
                SELECT da.drug_id,
                       BOOL_OR(COALESCE(query_state.status = 'matched', FALSE))
                           AS matched,
                       BOOL_OR(
                           query_state.drug_id IS NULL
                           OR (query_state.status = 'failed'
                               AND query_state.attempts < 3)
                       ) AS has_remaining,
                       BOOL_OR(COALESCE(
                           query_state.status = 'failed'
                           AND query_state.attempts >= 3,
                           FALSE
                       )) AS has_terminal_failure,
                       BOOL_OR(COALESCE(
                           query_state.status = 'context_conflict',
                           FALSE
                       )) AS has_context_conflict
                FROM drug_aliases da
                LEFT JOIN drug_public_enrichment_queries query_state
                  ON query_state.drug_id = da.drug_id
                 AND query_state.source = 'pubchem'
                 AND query_state.normalized_query = da.normalized_value
                WHERE da.alias_type IN (
                    'primary_name_candidate', 'development_code', 'display_name'
                )
                GROUP BY da.drug_id
            )
            SELECT
                (SELECT COUNT(*) FROM per_drug) AS eligible_drugs,
                (SELECT COUNT(*) FROM per_drug WHERE matched) AS matched_drugs,
                (SELECT COUNT(*) FROM per_drug
                 WHERE NOT matched AND NOT has_remaining
                   AND NOT has_terminal_failure
                   AND NOT has_context_conflict) AS exhausted_drugs,
                (SELECT COUNT(*) FROM per_drug
                 WHERE NOT matched AND NOT has_remaining
                   AND has_terminal_failure) AS failed_drugs,
                (SELECT COUNT(*) FROM per_drug
                 WHERE NOT matched AND NOT has_remaining
                   AND NOT has_terminal_failure
                   AND has_context_conflict) AS context_conflict_drugs,
                (SELECT COUNT(*) FROM per_drug
                 WHERE NOT matched AND has_remaining) AS pending_drugs,
                (SELECT COUNT(*) FROM drug_public_enrichment_queries
                 WHERE source = 'pubchem') AS alias_queries_attempted,
                (SELECT COUNT(*) FROM drug_public_enrichment_queries
                 WHERE source = 'pubchem' AND status = 'matched') AS matched_queries,
                (SELECT COUNT(*) FROM drug_public_enrichment_queries
                 WHERE source = 'pubchem' AND status = 'not_found') AS not_found_queries,
                (SELECT COUNT(*) FROM drug_public_enrichment_queries
                 WHERE source = 'pubchem' AND status = 'failed') AS failed_queries,
                (SELECT COUNT(*) FROM drug_public_enrichment_queries
                 WHERE source = 'pubchem' AND status = 'context_conflict')
                    AS context_conflict_queries,
                (SELECT COUNT(DISTINCT drug_id) FROM drug_identifiers
                 WHERE source = 'pubchem' AND identifier_type = 'pubchem_cid')
                    AS drugs_with_cid,
                (SELECT COUNT(DISTINCT drug_id) FROM drug_identifiers
                 WHERE source = 'pubchem' AND identifier_type = 'inchikey')
                    AS drugs_with_inchikey,
                (SELECT COUNT(DISTINCT drug_id) FROM drug_identifiers
                 WHERE source = 'pubchem'
                   AND identifier_type = 'connectivity_smiles')
                    AS drugs_with_smiles
        """)).mappings().one()
    result = dict(row)
    eligible = int(result["eligible_drugs"] or 0)
    matched = int(result["matched_drugs"] or 0)
    exhausted = int(result["exhausted_drugs"] or 0)
    failed = int(result["failed_drugs"] or 0)
    context_conflicts = int(result["context_conflict_drugs"] or 0)
    represented = matched + exhausted + failed + context_conflicts
    result["unattempted_or_in_progress_drugs"] = max(0, eligible - represented)
    result["terminal_coverage_pct"] = round(100 * represented / eligible, 2) if eligible else 0.0
    result["match_rate_pct"] = round(
        100 * matched / (matched + exhausted),
        2,
    ) if matched + exhausted else 0.0
    result["source"] = "pubchem_pug_rest"
    return result


def _normalized_name(value: str | None) -> str:
    return "".join(character for character in (value or "").casefold() if character.isalnum())


def _name_tokens(value: str | None) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]{3,}", (value or "").casefold())
    }


def pubchem_validation_status(*, sample_limit: int = 25) -> dict:
    """Audit identifier consistency and expose title-divergent matches for review."""
    sample_limit = max(1, min(100, sample_limit))
    status = pubchem_enrichment_status()
    with get_cortellis_session() as session:
        integrity = dict(session.execute(text("""
            SELECT
                (SELECT COUNT(*)
                 FROM drug_public_enrichment_state state
                 WHERE state.source = 'pubchem' AND state.status = 'matched'
                   AND NOT EXISTS (
                       SELECT 1 FROM drug_identifiers identifier
                       WHERE identifier.drug_id = state.drug_id
                         AND identifier.source = 'pubchem'
                         AND identifier.identifier_type = 'pubchem_cid'
                   )) AS matched_without_cid,
                (SELECT COUNT(*)
                 FROM drug_identifiers identifier
                 WHERE identifier.source = 'pubchem'
                   AND identifier.identifier_type = 'pubchem_cid'
                   AND NOT EXISTS (
                       SELECT 1 FROM drug_public_enrichment_state state
                       WHERE state.drug_id = identifier.drug_id
                         AND state.source = 'pubchem'
                         AND state.status = 'matched'
                   )) AS cid_without_matched_state,
                (SELECT COUNT(*)
                 FROM drug_identifiers
                 WHERE source = 'pubchem' AND identifier_type = 'pubchem_cid'
                   AND (
                       evidence->>'pubchem_cid' IS DISTINCT FROM identifier_value
                       OR source_reference NOT LIKE '%' || identifier_value
                   )) AS cid_provenance_mismatches,
                (SELECT COUNT(*)
                 FROM drug_identifiers
                 WHERE source = 'pubchem' AND identifier_type = 'inchikey'
                   AND normalized_value !~ '^[A-Z]{14}-[A-Z]{10}-[A-Z]$')
                    AS invalid_inchikeys,
                (SELECT COUNT(*)
                 FROM drug_public_enrichment_queries query
                 WHERE query.source = 'pubchem' AND query.status = 'matched'
                   AND NOT EXISTS (
                       SELECT 1 FROM drug_public_enrichment_state state
                       WHERE state.drug_id = query.drug_id
                         AND state.source = 'pubchem'
                         AND state.status = 'matched'
                   )) AS matched_query_state_mismatches,
                (SELECT COUNT(*) FROM (
                    SELECT identifier_value
                    FROM drug_identifiers
                    WHERE source = 'pubchem'
                      AND identifier_type = 'pubchem_cid'
                    GROUP BY identifier_value
                    HAVING COUNT(DISTINCT drug_id) > 1
                ) duplicates) AS shared_cids
        """)).mappings().one())
        rows = session.execute(text("""
            SELECT drug_id, identifier_value, source_reference, evidence
            FROM drug_identifiers
            WHERE source = 'pubchem' AND identifier_type = 'pubchem_cid'
            ORDER BY md5(drug_id::text || ':' || identifier_value)
        """)).mappings().all()

    normalized_exact = 0
    token_overlap = 0
    divergent = []
    for row in rows:
        evidence = row["evidence"] or {}
        query_name = evidence.get("query_name")
        title = evidence.get("pubchem_title")
        if _normalized_name(query_name) == _normalized_name(title):
            normalized_exact += 1
        has_overlap = bool(_name_tokens(query_name) & _name_tokens(title))
        if has_overlap:
            token_overlap += 1
        elif len(divergent) < sample_limit:
            divergent.append({
                "drug_id": row["drug_id"],
                "pubchem_cid": row["identifier_value"],
                "query_name": query_name,
                "pubchem_title": title,
                "source_reference": row["source_reference"],
            })

    matched = len(rows)
    report = {
        **status,
        **integrity,
        "matched_title_normalized_exact_pct": round(
            100 * normalized_exact / matched,
            2,
        ) if matched else 0.0,
        "matched_title_token_overlap_pct": round(
            100 * token_overlap / matched,
            2,
        ) if matched else 0.0,
        "title_divergent_review_sample": divergent,
        "title_divergent_matches": matched - token_overlap,
    }
    report["identifier_integrity_ready"] = bool(
        report["drugs_with_cid"] > 0
        and not report["matched_without_cid"]
        and not report["cid_without_matched_state"]
        and not report["cid_provenance_mismatches"]
        and not report["invalid_inchikeys"]
        and not report["matched_query_state_mismatches"]
    )
    report["coverage_complete"] = bool(
        report["terminal_coverage_pct"] == 100.0
        and not report["failed_drugs"]
    )
    return report
