"""Conservative, resumable public identifier enrichment from PubChem PUG REST."""

from __future__ import annotations

from dataclasses import dataclass
import json
import time
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from sqlalchemy import text

from unified_api.services.database import get_cortellis_session
from unified_api.services.entity_resolution import EntityResolutionService


PUBCHEM_BASE_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"


@dataclass(frozen=True)
class PubChemMatch:
    cid: int
    title: str
    inchikey: str | None
    connectivity_smiles: str | None


class PubChemClient:
    def __init__(self, *, timeout: float = 20, delay_seconds: float = 0.22):
        self.timeout = timeout
        self.delay_seconds = delay_seconds

    def lookup_name(self, name: str) -> PubChemMatch | None:
        encoded = quote(name, safe="")
        url = (
            f"{PUBCHEM_BASE_URL}/compound/name/{encoded}/property/"
            "Title,InChIKey,ConnectivitySMILES/JSON"
        )
        request = Request(url, headers={"User-Agent": "OneBD/1.0 admin@pchomelab.com"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.load(response)
        except HTTPError as exc:
            if exc.code == 404:
                return None
            raise
        finally:
            if self.delay_seconds:
                time.sleep(self.delay_seconds)
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


def _candidates(batch_size: int) -> list[dict]:
    with get_cortellis_session() as session:
        return [dict(row) for row in session.execute(text("""
            SELECT drug_id, alias_value AS query_name
            FROM (
                SELECT da.drug_id, da.alias_value,
                       ROW_NUMBER() OVER (
                           PARTITION BY da.drug_id
                           ORDER BY CASE da.alias_type
                               WHEN 'primary_name_candidate' THEN 1
                               WHEN 'development_code' THEN 2
                               ELSE 3 END,
                               LENGTH(da.alias_value)
                       ) AS position
                FROM drug_aliases da
                LEFT JOIN drug_public_enrichment_state state
                  ON state.drug_id = da.drug_id AND state.source = 'pubchem'
                WHERE da.alias_type IN (
                    'primary_name_candidate', 'development_code', 'display_name'
                )
                  AND (
                    state.drug_id IS NULL OR
                    (state.status = 'failed' AND state.attempts < 3
                     AND state.next_retry_at <= NOW())
                  )
            ) candidates
            WHERE position = 1
            ORDER BY drug_id
            LIMIT :batch_size
        """), {"batch_size": batch_size}).mappings().all()]


def enrich_pubchem_batch(
    *, batch_size: int = 100, client: PubChemClient | None = None
) -> dict:
    ensure_pubchem_schema()
    client = client or PubChemClient()
    candidates = _candidates(batch_size)
    matched = 0
    not_found = 0
    failed = 0
    for candidate in candidates:
        drug_id = candidate["drug_id"]
        query_name = candidate["query_name"]
        try:
            match = client.lookup_name(query_name)
            if match is None:
                not_found += 1
                with get_cortellis_session() as session:
                    _record_state(session, drug_id, query_name, "not_found")
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
            matched += 1
        except Exception as exc:
            failed += 1
            with get_cortellis_session() as session:
                _record_state(
                    session, drug_id, query_name, "failed", error=str(exc)[:2000]
                )
    return {
        "status": "completed" if failed == 0 else "partial",
        "processed": len(candidates),
        "matched": matched,
        "not_found": not_found,
        "failed": failed,
    }


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
