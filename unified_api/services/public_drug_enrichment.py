"""Exact ChEMBL and Open Targets enrichment for Cortellis drug identities."""

from __future__ import annotations

from collections import defaultdict
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
from unified_api.services.entity_resolution import (
    EntityResolutionService,
    normalize_identifier_value,
)
from unified_api.services.public_source_http import (
    PublicSourceHttpClient,
    RetryPolicy,
)


CHEMBL_SOURCE = "chembl_api"
OPEN_TARGETS_SOURCE = "open_targets_graphql"
_public_drug_schema_ready = False

CHEMBL_NONPROPRIETARY_ALIAS_TYPES = {
    "INN": "inn",
    "INN_FRENCH": "inn_french",
    "INN_SPANISH": "inn_spanish",
    "USAN": "usan",
    "BAN": "ban",
    "JAN": "jan",
    "FDA": "fda_name",
    "EMA": "ema_name",
    "USP": "usp_name",
    "DCF": "dcf_name",
}


def is_conservative_development_code(value: str) -> bool:
    """Accept source-typed research codes while rejecting words and prose."""
    value = str(value or "").strip()
    return bool(
        3 <= len(value) <= 50
        and len(value.split()) <= 3
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 .,/+_-]*", value)
        and re.search(r"[A-Za-z]", value)
        and re.search(r"\d", value)
    )


def classify_chembl_synonym(
    synonym: dict[str, Any],
) -> tuple[str, str, float] | None:
    """Classify only authoritative nonproprietary names or research codes."""
    source_type = str(synonym.get("syn_type") or "").strip().upper()
    value = str(
        synonym.get("molecule_synonym") or synonym.get("synonyms") or ""
    ).strip()
    if not value:
        return None
    alias_type = CHEMBL_NONPROPRIETARY_ALIAS_TYPES.get(source_type)
    if alias_type:
        return alias_type, value, 1.0
    if source_type == "RESEARCH_CODE" and is_conservative_development_code(value):
        return "development_code", value, 0.95
    return None


def chembl_typed_aliases(
    molecule: dict[str, Any],
) -> list[tuple[str, str, float, str]]:
    """Return normalized, deduplicated typed aliases from one ChEMBL record."""
    aliases: list[tuple[str, str, float, str]] = []
    seen: set[tuple[str, str]] = set()
    for synonym in molecule.get("molecule_synonyms") or []:
        if not isinstance(synonym, dict):
            continue
        classified = classify_chembl_synonym(synonym)
        if not classified:
            continue
        alias_type, alias_value, confidence = classified
        normalized = normalize_identifier_value("drug_alias", alias_value)
        identity = (alias_type, normalized)
        if not normalized or identity in seen:
            continue
        seen.add(identity)
        aliases.append((
            alias_type,
            alias_value,
            confidence,
            str(synonym.get("syn_type") or "").strip().upper(),
        ))
    return aliases


class ChEMBLClient:
    """Typed subset of the official ChEMBL data web services."""

    def __init__(self, *, base_url: str | None = None):
        self._http = PublicSourceHttpClient(
            source=CHEMBL_SOURCE,
            base_url=base_url or settings.chembl_base_url,
            user_agent=settings.public_data_user_agent,
            timeout=45,
            min_interval_seconds=settings.chembl_request_interval_seconds,
            retry_policy=RetryPolicy(max_retries=3),
        )

    def status(self) -> dict[str, Any]:
        response = self._http.get_json("/status.json", use_cache=True)
        if response is None:
            raise RuntimeError("ChEMBL status response was empty")
        return response.payload

    def molecules_by_inchikeys(self, inchikeys: list[str]) -> dict[str, Any]:
        if not inchikeys:
            return {"molecules": [], "page_meta": {"total_count": 0}}
        for inchikey in inchikeys:
            if not re.fullmatch(r"[A-Z]{14}-[A-Z]{10}-[A-Z]", inchikey):
                raise ValueError(f"Invalid InChIKey: {inchikey}")
        response = self._http.get_json("/molecule.json", {
            "molecule_structures__standard_inchi_key__in": ",".join(inchikeys),
            "limit": max(100, len(inchikeys) * 5),
        })
        if response is None:
            raise RuntimeError("ChEMBL molecule response was empty")
        payload = response.payload
        molecules = payload.get("molecules")
        if not isinstance(molecules, list):
            raise ValueError("ChEMBL returned a non-list molecules payload")
        total = int((payload.get("page_meta") or {}).get("total_count") or 0)
        if total > len(molecules):
            raise ValueError(
                "ChEMBL exact identifier response exceeded the requested page limit"
            )
        return payload


class OpenTargetsClient:
    """Batched, exact-ChEMBL-ID adapter for Open Targets GraphQL."""

    DRUG_SELECTION = """
        id
        name
        description
        drugType
        maximumClinicalStage
        synonyms { label source }
        tradeNames { label source }
        crossReferences { source ids }
        indications {
          count
          rows { id maxClinicalStage disease { id name } }
        }
        mechanismsOfAction {
          rows {
            mechanismOfAction
            actionType
            targetName
            targets {
              id
              approvedSymbol
              approvedName
              biotype
              proteinIds { id source }
            }
            references { source ids urls }
          }
        }
    """

    def __init__(self, *, base_url: str | None = None):
        self._http = PublicSourceHttpClient(
            source=OPEN_TARGETS_SOURCE,
            base_url=base_url or settings.open_targets_base_url,
            user_agent=settings.public_data_user_agent,
            timeout=60,
            min_interval_seconds=settings.open_targets_request_interval_seconds,
            retry_policy=RetryPolicy(max_retries=3),
        )

    def _graphql(self, query: str, *, use_cache: bool = False) -> dict[str, Any]:
        response = self._http.post_json(
            "/graphql",
            {"query": query},
            use_cache=use_cache,
        )
        if response is None:
            raise RuntimeError("Open Targets GraphQL response was empty")
        payload = response.payload
        if payload.get("errors"):
            messages = "; ".join(
                str(error.get("message") or error)
                for error in payload["errors"]
            )
            raise ValueError(f"Open Targets GraphQL errors: {messages}")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ValueError("Open Targets returned no GraphQL data object")
        return data

    def metadata(self) -> dict[str, Any]:
        return self._graphql("""
            query {
              meta {
                product
                name
                dataVersion { year month iteration }
                apiVersion { x y z }
              }
            }
        """, use_cache=True)["meta"]

    def drugs(self, chembl_ids: list[str]) -> tuple[dict[str, Any], dict[str, Any]]:
        if not chembl_ids:
            return {}, self.metadata()
        for chembl_id in chembl_ids:
            if not re.fullmatch(r"CHEMBL\d+", chembl_id):
                raise ValueError(f"Invalid ChEMBL ID: {chembl_id}")
        selections = "\n".join(
            f'd{index}: drug(chemblId: "{chembl_id}") {{'
            f"{self.DRUG_SELECTION}" "}"
            for index, chembl_id in enumerate(chembl_ids)
        )
        query = f"""
            query {{
              {selections}
              meta {{
                product
                name
                dataVersion {{ year month iteration }}
                apiVersion {{ x y z }}
              }}
            }}
        """
        data = self._graphql(query)
        metadata = data.pop("meta")
        return {
            chembl_id: data.get(f"d{index}")
            for index, chembl_id in enumerate(chembl_ids)
        }, metadata


def _open_targets_version(metadata: dict[str, Any]) -> str:
    version = metadata.get("dataVersion") or {}
    parts = [version.get("year"), version.get("month"), version.get("iteration")]
    return ".".join(str(part) for part in parts if part not in {None, ""})


def ensure_public_drug_schema() -> None:
    """Create exact-source state, retained profiles, and canonical target tables."""
    global _public_drug_schema_ready
    if _public_drug_schema_ready:
        return
    from unified_api.services.runtime_schema import runtime_schema_is_pre_migrated

    if runtime_schema_is_pre_migrated():
        _public_drug_schema_ready = True
        return
    EntityResolutionService().ensure_identity_schema()
    with get_cortellis_session() as session:
        session.execute(text("""
            ALTER TABLE drug_identifiers
            DROP CONSTRAINT IF EXISTS
                drug_identifiers_identifier_type_normalized_value_key
        """))
        session.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_drug_identifier_identity
            ON drug_identifiers (drug_id, identifier_type, normalized_value)
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS public_drug_source_state (
                drug_id INTEGER NOT NULL REFERENCES drugs(id) ON DELETE CASCADE,
                source VARCHAR(100) NOT NULL,
                source_identifier VARCHAR(500) NOT NULL,
                status VARCHAR(20) NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                source_version VARCHAR(50),
                last_error TEXT,
                last_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                next_retry_at TIMESTAMPTZ,
                PRIMARY KEY (drug_id, source, source_identifier)
            )
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_public_drug_source_state_queue
            ON public_drug_source_state (
                source, source_version, status, next_retry_at, drug_id
            )
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS drug_chembl_records (
                drug_id INTEGER NOT NULL REFERENCES drugs(id) ON DELETE CASCADE,
                chembl_id VARCHAR(30) NOT NULL,
                standard_inchi_key VARCHAR(100) NOT NULL,
                preferred_name TEXT,
                molecule_type VARCHAR(100),
                max_phase FLOAT,
                first_approval INTEGER,
                source_version VARCHAR(50) NOT NULL,
                source_url TEXT NOT NULL,
                raw_sha256 CHAR(64) NOT NULL,
                raw_payload JSONB NOT NULL,
                first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (drug_id, chembl_id)
            )
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS drug_chembl_record_history (
                drug_id INTEGER NOT NULL REFERENCES drugs(id) ON DELETE CASCADE,
                chembl_id VARCHAR(30) NOT NULL,
                response_sha256 CHAR(64) NOT NULL,
                source_version VARCHAR(50) NOT NULL,
                raw_payload JSONB NOT NULL,
                first_fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (drug_id, chembl_id, response_sha256)
            )
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS public_drug_profiles (
                drug_id INTEGER NOT NULL REFERENCES drugs(id) ON DELETE CASCADE,
                chembl_id VARCHAR(30) NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                drug_type VARCHAR(100),
                maximum_clinical_stage VARCHAR(50),
                synonyms JSONB NOT NULL DEFAULT '[]'::jsonb,
                trade_names JSONB NOT NULL DEFAULT '[]'::jsonb,
                cross_references JSONB NOT NULL DEFAULT '[]'::jsonb,
                source VARCHAR(100) NOT NULL,
                source_version VARCHAR(50) NOT NULL,
                source_url TEXT NOT NULL,
                raw_sha256 CHAR(64) NOT NULL,
                raw_payload JSONB NOT NULL,
                first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (drug_id, chembl_id)
            )
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS public_drug_profile_history (
                drug_id INTEGER NOT NULL REFERENCES drugs(id) ON DELETE CASCADE,
                chembl_id VARCHAR(30) NOT NULL,
                response_sha256 CHAR(64) NOT NULL,
                source_version VARCHAR(50) NOT NULL,
                raw_payload JSONB NOT NULL,
                first_fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (drug_id, chembl_id, response_sha256)
            )
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS public_targets (
                ensembl_id VARCHAR(30) PRIMARY KEY,
                approved_symbol VARCHAR(100) NOT NULL,
                approved_name TEXT NOT NULL,
                biotype VARCHAR(100),
                protein_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                source VARCHAR(100) NOT NULL,
                source_version VARCHAR(50) NOT NULL,
                first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_public_targets_symbol
            ON public_targets (approved_symbol)
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS public_diseases (
                disease_id VARCHAR(100) PRIMARY KEY,
                name TEXT NOT NULL,
                source VARCHAR(100) NOT NULL,
                source_version VARCHAR(50) NOT NULL,
                first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS public_drug_target_links (
                drug_id INTEGER NOT NULL REFERENCES drugs(id) ON DELETE CASCADE,
                chembl_id VARCHAR(30) NOT NULL,
                ensembl_id VARCHAR(30) NOT NULL REFERENCES public_targets(ensembl_id)
                    ON DELETE CASCADE,
                mechanism_hash CHAR(64) NOT NULL,
                mechanism_of_action TEXT,
                action_type VARCHAR(100),
                target_name TEXT,
                source_references JSONB NOT NULL DEFAULT '[]'::jsonb,
                source VARCHAR(100) NOT NULL,
                source_version VARCHAR(50) NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (drug_id, chembl_id, ensembl_id, mechanism_hash)
            )
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_public_drug_target_target
            ON public_drug_target_links (ensembl_id, drug_id)
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS public_drug_disease_links (
                drug_id INTEGER NOT NULL REFERENCES drugs(id) ON DELETE CASCADE,
                chembl_id VARCHAR(30) NOT NULL,
                disease_id VARCHAR(100) NOT NULL
                    REFERENCES public_diseases(disease_id) ON DELETE CASCADE,
                maximum_clinical_stage VARCHAR(50),
                source_record_id VARCHAR(100),
                source VARCHAR(100) NOT NULL,
                source_version VARCHAR(50) NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (drug_id, chembl_id, disease_id)
            )
        """))
    _public_drug_schema_ready = True


def _record_state(
    session,
    *,
    drug_id: int,
    source: str,
    source_identifier: str,
    status: str,
    source_version: str,
    error: str | None = None,
) -> None:
    session.execute(text("""
        INSERT INTO public_drug_source_state (
            drug_id, source, source_identifier, status, attempts,
            source_version, last_error, next_retry_at
        ) VALUES (
            :drug_id, :source, :source_identifier, :status, 1,
            :source_version, :error,
            CASE WHEN :status = 'failed' THEN NOW() + INTERVAL '30 minutes' END
        ) ON CONFLICT (drug_id, source, source_identifier) DO UPDATE SET
            status = EXCLUDED.status,
            attempts = CASE
                WHEN public_drug_source_state.source_version
                     IS DISTINCT FROM EXCLUDED.source_version THEN 1
                ELSE public_drug_source_state.attempts + 1
            END,
            source_version = EXCLUDED.source_version,
            last_error = EXCLUDED.last_error,
            last_attempt_at = NOW(),
            next_retry_at = EXCLUDED.next_retry_at
    """), {
        "drug_id": drug_id,
        "source": source,
        "source_identifier": source_identifier,
        "status": status,
        "source_version": source_version,
        "error": error[:4000] if error else None,
    })


def _chembl_candidates(source_version: str, batch_size: int) -> list[dict[str, Any]]:
    with get_cortellis_session() as session:
        return [dict(row) for row in session.execute(text("""
            SELECT identifier.drug_id,
                   UPPER(identifier.identifier_value) AS inchikey
            FROM drug_identifiers identifier
            LEFT JOIN public_drug_source_state state
              ON state.drug_id = identifier.drug_id
             AND state.source = :source
             AND state.source_identifier = UPPER(identifier.identifier_value)
            WHERE identifier.identifier_type = 'inchikey'
              AND (
                state.drug_id IS NULL OR
                state.source_version IS DISTINCT FROM :source_version OR
                (state.status = 'failed' AND state.attempts < 3
                 AND state.next_retry_at <= NOW())
              )
            ORDER BY identifier.drug_id
            LIMIT :batch_size
        """), {
            "source": CHEMBL_SOURCE,
            "source_version": source_version,
            "batch_size": batch_size,
        }).mappings().all()]


def _upsert_chembl_typed_aliases(
    session,
    *,
    drug_id: int,
    chembl_id: str,
    inchikey: str,
    molecule: dict[str, Any],
    source_version: str,
    source_url: str,
) -> int:
    """Index only ChEMBL's typed, structure-backed drug-name evidence."""
    written = 0
    for alias_type, alias_value, confidence, synonym_type in chembl_typed_aliases(
        molecule
    ):
        evidence = json.dumps({
            "match_method": "exact_standard_inchikey",
            "inchikey": inchikey,
            "chembl_id": chembl_id,
            "chembl_release": source_version,
            "chembl_synonym_type": synonym_type,
        }, sort_keys=True)
        result = session.execute(text("""
            INSERT INTO drug_aliases (
                drug_id, alias_type, alias_value, normalized_value,
                source, source_reference, evidence, confidence, review_status
            ) VALUES (
                :drug_id, :alias_type, :alias_value, :normalized_value,
                :source, :source_url, CAST(:evidence AS JSONB),
                :confidence, 'auto_accepted'
            ) ON CONFLICT (drug_id, alias_type, normalized_value) DO UPDATE SET
                alias_value = EXCLUDED.alias_value,
                source = EXCLUDED.source,
                source_reference = EXCLUDED.source_reference,
                evidence = EXCLUDED.evidence,
                confidence = EXCLUDED.confidence,
                review_status = EXCLUDED.review_status
            RETURNING id
        """), {
            "drug_id": drug_id,
            "alias_type": alias_type,
            "alias_value": alias_value,
            "normalized_value": normalize_identifier_value(
                "drug_alias", alias_value
            ),
            "source": CHEMBL_SOURCE,
            "source_url": source_url,
            "evidence": evidence,
            "confidence": confidence,
        }).scalar()
        written += int(result is not None)
    return written


def _upsert_chembl_record(
    session,
    *,
    drug_id: int,
    inchikey: str,
    molecule: dict[str, Any],
    source_version: str,
) -> int:
    chembl_id = str(molecule["molecule_chembl_id"])
    raw_json = json.dumps(molecule, sort_keys=True, separators=(",", ":"))
    raw_sha = hashlib.sha256(raw_json.encode()).hexdigest()
    source_url = f"https://www.ebi.ac.uk/chembl/explore/compound/{chembl_id}"
    session.execute(text("""
        INSERT INTO drug_chembl_records (
            drug_id, chembl_id, standard_inchi_key, preferred_name,
            molecule_type, max_phase, first_approval, source_version,
            source_url, raw_sha256, raw_payload
        ) VALUES (
            :drug_id, :chembl_id, :inchikey, :preferred_name,
            :molecule_type, :max_phase, :first_approval, :source_version,
            :source_url, :raw_sha, CAST(:raw_payload AS JSONB)
        ) ON CONFLICT (drug_id, chembl_id) DO UPDATE SET
            standard_inchi_key = EXCLUDED.standard_inchi_key,
            preferred_name = EXCLUDED.preferred_name,
            molecule_type = EXCLUDED.molecule_type,
            max_phase = EXCLUDED.max_phase,
            first_approval = EXCLUDED.first_approval,
            source_version = EXCLUDED.source_version,
            source_url = EXCLUDED.source_url,
            raw_sha256 = EXCLUDED.raw_sha256,
            raw_payload = EXCLUDED.raw_payload,
            last_seen_at = NOW()
    """), {
        "drug_id": drug_id,
        "chembl_id": chembl_id,
        "inchikey": inchikey,
        "preferred_name": molecule.get("pref_name"),
        "molecule_type": molecule.get("molecule_type"),
        "max_phase": molecule.get("max_phase"),
        "first_approval": molecule.get("first_approval"),
        "source_version": source_version,
        "source_url": source_url,
        "raw_sha": raw_sha,
        "raw_payload": raw_json,
    })
    session.execute(text("""
        INSERT INTO drug_chembl_record_history (
            drug_id, chembl_id, response_sha256, source_version, raw_payload
        ) VALUES (
            :drug_id, :chembl_id, :raw_sha, :source_version,
            CAST(:raw_payload AS JSONB)
        ) ON CONFLICT (drug_id, chembl_id, response_sha256) DO UPDATE SET
            last_fetched_at = NOW()
    """), {
        "drug_id": drug_id,
        "chembl_id": chembl_id,
        "raw_sha": raw_sha,
        "source_version": source_version,
        "raw_payload": raw_json,
    })
    evidence = json.dumps({
        "match_method": "exact_standard_inchikey",
        "inchikey": inchikey,
        "chembl_release": source_version,
    })
    session.execute(text("""
        INSERT INTO drug_identifiers (
            drug_id, identifier_type, identifier_value, normalized_value,
            source, source_reference, evidence, confidence, review_status
        ) VALUES (
            :drug_id, 'chembl_id', :chembl_id, :chembl_id,
            :source, :source_url, CAST(:evidence AS JSONB), 1.0,
            'auto_accepted'
        ) ON CONFLICT (drug_id, identifier_type, normalized_value) DO UPDATE SET
            source = EXCLUDED.source,
            source_reference = EXCLUDED.source_reference,
            evidence = EXCLUDED.evidence,
            confidence = EXCLUDED.confidence,
            updated_at = NOW()
    """), {
        "drug_id": drug_id,
        "chembl_id": chembl_id,
        "source": CHEMBL_SOURCE,
        "source_url": source_url,
        "evidence": evidence,
    })
    preferred_name = str(molecule.get("pref_name") or "").strip()
    if preferred_name:
        session.execute(text("""
            INSERT INTO drug_aliases (
                drug_id, alias_type, alias_value, normalized_value,
                source, source_reference, evidence, confidence, review_status
            ) VALUES (
                :drug_id, 'chembl_preferred_name', :alias_value,
                :normalized_value, :source, :source_url,
                CAST(:evidence AS JSONB), 1.0, 'auto_accepted'
            ) ON CONFLICT (drug_id, alias_type, normalized_value) DO UPDATE SET
                source_reference = EXCLUDED.source_reference,
                evidence = EXCLUDED.evidence,
                confidence = EXCLUDED.confidence
        """), {
            "drug_id": drug_id,
            "alias_value": preferred_name,
            "normalized_value": normalize_identifier_value(
                "drug_alias", preferred_name
            ),
            "source": CHEMBL_SOURCE,
            "source_url": source_url,
            "evidence": evidence,
        })
    _upsert_chembl_typed_aliases(
        session,
        drug_id=drug_id,
        chembl_id=chembl_id,
        inchikey=inchikey,
        molecule=molecule,
        source_version=source_version,
        source_url=source_url,
    )
    return 1


def enrich_chembl_identifiers(
    *,
    batch_size: int = 100,
    client: ChEMBLClient | None = None,
) -> dict[str, Any]:
    """Map PubChem-confirmed structures to ChEMBL without name inference."""
    ensure_public_drug_schema()
    lock = get_cortellis_engine().connect()
    acquired = bool(lock.execute(text(
        "SELECT pg_try_advisory_lock(hashtext('onebd_chembl_enrichment'))"
    )).scalar())
    if not acquired:
        lock.close()
        return {"status": "skipped", "reason": "ChEMBL enrichment already running"}
    try:
        client = client or ChEMBLClient()
        source_status = client.status()
        source_version = str(source_status["chembl_db_version"])
        candidates = _chembl_candidates(source_version, batch_size)
        if not candidates:
            return {
                "status": "completed",
                "processed": 0,
                "matched": 0,
                "not_found": 0,
                "identifiers_created": 0,
                "source_version": source_version,
                "source_data_at": source_status.get("chembl_release_date"),
            }
        payload = client.molecules_by_inchikeys([
            candidate["inchikey"] for candidate in candidates
        ])
        by_inchikey: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for molecule in payload["molecules"]:
            structures = molecule.get("molecule_structures") or {}
            key = str(structures.get("standard_inchi_key") or "").upper()
            if key:
                by_inchikey[key].append(molecule)
        matched = 0
        not_found = 0
        identifiers = 0
        with get_cortellis_session() as session:
            for candidate in candidates:
                molecules = by_inchikey.get(candidate["inchikey"], [])
                if not molecules:
                    not_found += 1
                    _record_state(
                        session,
                        drug_id=candidate["drug_id"],
                        source=CHEMBL_SOURCE,
                        source_identifier=candidate["inchikey"],
                        status="not_found",
                        source_version=source_version,
                    )
                    continue
                matched += 1
                for molecule in molecules:
                    identifiers += _upsert_chembl_record(
                        session,
                        drug_id=candidate["drug_id"],
                        inchikey=candidate["inchikey"],
                        molecule=molecule,
                        source_version=source_version,
                    )
                _record_state(
                    session,
                    drug_id=candidate["drug_id"],
                    source=CHEMBL_SOURCE,
                    source_identifier=candidate["inchikey"],
                    status="matched",
                    source_version=source_version,
                )
        return {
            "status": "completed",
            "processed": len(candidates),
            "matched": matched,
            "not_found": not_found,
            "identifiers_created": identifiers,
            "source_version": source_version,
            "source_data_at": source_status.get("chembl_release_date"),
        }
    finally:
        try:
            lock.execute(text(
                "SELECT pg_advisory_unlock(hashtext('onebd_chembl_enrichment'))"
            ))
        finally:
            lock.close()


def backfill_chembl_typed_aliases(
    *,
    batch_size: int = 5000,
    after_drug_id: int = 0,
    after_chembl_id: str = "",
) -> dict[str, Any]:
    """Index typed aliases from retained exact-InChIKey ChEMBL records."""
    ensure_public_drug_schema()
    lock = get_cortellis_engine().connect()
    acquired = bool(lock.execute(text(
        "SELECT pg_try_advisory_lock(hashtext('onebd_chembl_enrichment'))"
    )).scalar())
    if not acquired:
        lock.close()
        return {"status": "skipped", "reason": "ChEMBL enrichment already running"}
    try:
        with get_cortellis_session() as session:
            records = session.execute(text("""
                SELECT drug_id, chembl_id, standard_inchi_key, source_version,
                       source_url, raw_payload
                FROM drug_chembl_records
                WHERE (drug_id, chembl_id) > (:after_drug_id, :after_chembl_id)
                ORDER BY drug_id, chembl_id
                LIMIT :batch_size
            """), {
                "after_drug_id": after_drug_id,
                "after_chembl_id": after_chembl_id,
                "batch_size": batch_size,
            }).mappings().all()
            aliases = 0
            for index, record in enumerate(records, start=1):
                aliases += _upsert_chembl_typed_aliases(
                    session,
                    drug_id=int(record["drug_id"]),
                    chembl_id=str(record["chembl_id"]),
                    inchikey=str(record["standard_inchi_key"]),
                    molecule=dict(record["raw_payload"]),
                    source_version=str(record["source_version"]),
                    source_url=str(record["source_url"]),
                )
                if index % 100 == 0:
                    session.commit()

            if records:
                last_drug_id = int(records[-1]["drug_id"])
                last_chembl_id = str(records[-1]["chembl_id"])
            else:
                last_drug_id = after_drug_id
                last_chembl_id = after_chembl_id
            remaining = int(session.execute(text("""
                SELECT COUNT(*) FROM drug_chembl_records
                WHERE (drug_id, chembl_id) > (:drug_id, :chembl_id)
            """), {
                "drug_id": last_drug_id,
                "chembl_id": last_chembl_id,
            }).scalar() or 0)
        return {
            "status": "completed",
            "processed": len(records),
            "aliases_upserted": aliases,
            "remaining": remaining,
            "next_after_drug_id": last_drug_id,
            "next_after_chembl_id": last_chembl_id,
        }
    finally:
        try:
            lock.execute(text(
                "SELECT pg_advisory_unlock(hashtext('onebd_chembl_enrichment'))"
            ))
        finally:
            lock.close()


def _open_targets_candidates(
    source_version: str,
    batch_size: int,
) -> list[dict[str, Any]]:
    with get_cortellis_session() as session:
        return [dict(row) for row in session.execute(text("""
            SELECT identifier.drug_id,
                   UPPER(identifier.identifier_value) AS chembl_id
            FROM drug_identifiers identifier
            LEFT JOIN public_drug_source_state state
              ON state.drug_id = identifier.drug_id
             AND state.source = :source
             AND state.source_identifier = UPPER(identifier.identifier_value)
            WHERE identifier.identifier_type = 'chembl_id'
              AND (
                state.drug_id IS NULL OR
                state.source_version IS DISTINCT FROM :source_version OR
                (state.status = 'failed' AND state.attempts < 3
                 AND state.next_retry_at <= NOW())
              )
            ORDER BY identifier.drug_id, identifier.identifier_value
            LIMIT :batch_size
        """), {
            "source": OPEN_TARGETS_SOURCE,
            "source_version": source_version,
            "batch_size": batch_size,
        }).mappings().all()]


def _upsert_open_targets_profile(
    session,
    *,
    drug_id: int,
    chembl_id: str,
    profile: dict[str, Any],
    source_version: str,
) -> int:
    raw_json = json.dumps(profile, sort_keys=True, separators=(",", ":"))
    raw_sha = hashlib.sha256(raw_json.encode()).hexdigest()
    source_url = f"https://platform.opentargets.org/drug/{chembl_id}"
    session.execute(text("""
        INSERT INTO public_drug_profiles (
            drug_id, chembl_id, name, description, drug_type,
            maximum_clinical_stage, synonyms, trade_names, cross_references,
            source, source_version, source_url, raw_sha256, raw_payload
        ) VALUES (
            :drug_id, :chembl_id, :name, :description, :drug_type,
            :maximum_clinical_stage, CAST(:synonyms AS JSONB),
            CAST(:trade_names AS JSONB), CAST(:cross_references AS JSONB),
            :source, :source_version, :source_url, :raw_sha,
            CAST(:raw_payload AS JSONB)
        ) ON CONFLICT (drug_id, chembl_id) DO UPDATE SET
            name = EXCLUDED.name,
            description = EXCLUDED.description,
            drug_type = EXCLUDED.drug_type,
            maximum_clinical_stage = EXCLUDED.maximum_clinical_stage,
            synonyms = EXCLUDED.synonyms,
            trade_names = EXCLUDED.trade_names,
            cross_references = EXCLUDED.cross_references,
            source = EXCLUDED.source,
            source_version = EXCLUDED.source_version,
            source_url = EXCLUDED.source_url,
            raw_sha256 = EXCLUDED.raw_sha256,
            raw_payload = EXCLUDED.raw_payload,
            last_seen_at = NOW()
    """), {
        "drug_id": drug_id,
        "chembl_id": chembl_id,
        "name": profile.get("name") or chembl_id,
        "description": profile.get("description"),
        "drug_type": profile.get("drugType"),
        "maximum_clinical_stage": profile.get("maximumClinicalStage"),
        "synonyms": json.dumps(profile.get("synonyms") or []),
        "trade_names": json.dumps(profile.get("tradeNames") or []),
        "cross_references": json.dumps(profile.get("crossReferences") or []),
        "source": OPEN_TARGETS_SOURCE,
        "source_version": source_version,
        "source_url": source_url,
        "raw_sha": raw_sha,
        "raw_payload": raw_json,
    })
    session.execute(text("""
        INSERT INTO public_drug_profile_history (
            drug_id, chembl_id, response_sha256, source_version, raw_payload
        ) VALUES (
            :drug_id, :chembl_id, :raw_sha, :source_version,
            CAST(:raw_payload AS JSONB)
        ) ON CONFLICT (drug_id, chembl_id, response_sha256) DO UPDATE SET
            last_fetched_at = NOW()
    """), {
        "drug_id": drug_id,
        "chembl_id": chembl_id,
        "raw_sha": raw_sha,
        "source_version": source_version,
        "raw_payload": raw_json,
    })
    primary_name = str(profile.get("name") or "").strip()
    if primary_name:
        session.execute(text("""
            INSERT INTO drug_aliases (
                drug_id, alias_type, alias_value, normalized_value,
                source, source_reference, evidence, confidence, review_status
            ) VALUES (
                :drug_id, 'open_targets_primary_name', :alias_value,
                :normalized_value, :source, :source_url,
                CAST(:evidence AS JSONB), 1.0, 'auto_accepted'
            ) ON CONFLICT (drug_id, alias_type, normalized_value) DO UPDATE SET
                source_reference = EXCLUDED.source_reference,
                evidence = EXCLUDED.evidence,
                confidence = EXCLUDED.confidence
        """), {
            "drug_id": drug_id,
            "alias_value": primary_name,
            "normalized_value": normalize_identifier_value(
                "drug_alias", primary_name
            ),
            "source": OPEN_TARGETS_SOURCE,
            "source_url": source_url,
            "evidence": json.dumps({
                "chembl_id": chembl_id,
                "open_targets_version": source_version,
            }),
        })

    session.execute(text("""
        DELETE FROM public_drug_target_links
        WHERE drug_id = :drug_id AND chembl_id = :chembl_id
    """), {"drug_id": drug_id, "chembl_id": chembl_id})
    session.execute(text("""
        DELETE FROM public_drug_disease_links
        WHERE drug_id = :drug_id AND chembl_id = :chembl_id
    """), {"drug_id": drug_id, "chembl_id": chembl_id})
    relationships = 0
    mechanisms = (profile.get("mechanismsOfAction") or {}).get("rows") or []
    for mechanism in mechanisms:
        source_references = mechanism.get("references") or []
        for target in mechanism.get("targets") or []:
            ensembl_id = str(target.get("id") or "")
            if not re.fullmatch(r"ENSG\d{11}", ensembl_id):
                continue
            session.execute(text("""
                INSERT INTO public_targets (
                    ensembl_id, approved_symbol, approved_name, biotype,
                    protein_ids, source, source_version
                ) VALUES (
                    :ensembl_id, :approved_symbol, :approved_name, :biotype,
                    CAST(:protein_ids AS JSONB), :source, :source_version
                ) ON CONFLICT (ensembl_id) DO UPDATE SET
                    approved_symbol = EXCLUDED.approved_symbol,
                    approved_name = EXCLUDED.approved_name,
                    biotype = EXCLUDED.biotype,
                    protein_ids = EXCLUDED.protein_ids,
                    source = EXCLUDED.source,
                    source_version = EXCLUDED.source_version,
                    last_seen_at = NOW()
            """), {
                "ensembl_id": ensembl_id,
                "approved_symbol": target.get("approvedSymbol") or ensembl_id,
                "approved_name": target.get("approvedName") or ensembl_id,
                "biotype": target.get("biotype"),
                "protein_ids": json.dumps(target.get("proteinIds") or []),
                "source": OPEN_TARGETS_SOURCE,
                "source_version": source_version,
            })
            mechanism_identity = json.dumps({
                "ensembl_id": ensembl_id,
                "mechanism": mechanism.get("mechanismOfAction"),
                "action_type": mechanism.get("actionType"),
            }, sort_keys=True)
            mechanism_hash = hashlib.sha256(mechanism_identity.encode()).hexdigest()
            inserted = session.execute(text("""
                INSERT INTO public_drug_target_links (
                    drug_id, chembl_id, ensembl_id, mechanism_hash,
                    mechanism_of_action, action_type, target_name,
                    source_references,
                    source, source_version
                ) VALUES (
                    :drug_id, :chembl_id, :ensembl_id, :mechanism_hash,
                    :mechanism, :action_type, :target_name,
                    CAST(:source_references AS JSONB), :source, :source_version
                ) ON CONFLICT DO NOTHING RETURNING drug_id
            """), {
                "drug_id": drug_id,
                "chembl_id": chembl_id,
                "ensembl_id": ensembl_id,
                "mechanism_hash": mechanism_hash,
                "mechanism": mechanism.get("mechanismOfAction"),
                "action_type": mechanism.get("actionType"),
                "target_name": mechanism.get("targetName"),
                "source_references": json.dumps(source_references),
                "source": OPEN_TARGETS_SOURCE,
                "source_version": source_version,
            }).scalar()
            relationships += int(inserted is not None)

    indications = (profile.get("indications") or {}).get("rows") or []
    for indication in indications:
        disease = indication.get("disease") or {}
        disease_id = str(disease.get("id") or "")
        if not disease_id:
            continue
        session.execute(text("""
            INSERT INTO public_diseases (
                disease_id, name, source, source_version
            ) VALUES (
                :disease_id, :name, :source, :source_version
            ) ON CONFLICT (disease_id) DO UPDATE SET
                name = EXCLUDED.name,
                source = EXCLUDED.source,
                source_version = EXCLUDED.source_version,
                last_seen_at = NOW()
        """), {
            "disease_id": disease_id,
            "name": disease.get("name") or disease_id,
            "source": OPEN_TARGETS_SOURCE,
            "source_version": source_version,
        })
        inserted = session.execute(text("""
            INSERT INTO public_drug_disease_links (
                drug_id, chembl_id, disease_id, maximum_clinical_stage,
                source_record_id, source, source_version
            ) VALUES (
                :drug_id, :chembl_id, :disease_id, :maximum_clinical_stage,
                :source_record_id, :source, :source_version
            ) ON CONFLICT (drug_id, chembl_id, disease_id) DO UPDATE SET
                maximum_clinical_stage = EXCLUDED.maximum_clinical_stage,
                source_record_id = EXCLUDED.source_record_id,
                source = EXCLUDED.source,
                source_version = EXCLUDED.source_version
            RETURNING drug_id
        """), {
            "drug_id": drug_id,
            "chembl_id": chembl_id,
            "disease_id": disease_id,
            "maximum_clinical_stage": indication.get("maxClinicalStage"),
            "source_record_id": indication.get("id"),
            "source": OPEN_TARGETS_SOURCE,
            "source_version": source_version,
        }).scalar()
        relationships += int(inserted is not None)
    return relationships


def enrich_open_targets_profiles(
    *,
    batch_size: int = 10,
    client: OpenTargetsClient | None = None,
) -> dict[str, Any]:
    """Enrich exact ChEMBL mappings with targets, indications, and drug profiles."""
    ensure_public_drug_schema()
    lock = get_cortellis_engine().connect()
    acquired = bool(lock.execute(text(
        "SELECT pg_try_advisory_lock(hashtext('onebd_open_targets_enrichment'))"
    )).scalar())
    if not acquired:
        lock.close()
        return {
            "status": "skipped",
            "reason": "Open Targets enrichment already running",
        }
    try:
        client = client or OpenTargetsClient()
        metadata = client.metadata()
        source_version = _open_targets_version(metadata)
        candidates = _open_targets_candidates(source_version, batch_size)
        if not candidates:
            return {
                "status": "completed",
                "processed": 0,
                "matched": 0,
                "not_found": 0,
                "relationships_created": 0,
                "source_version": source_version,
            }
        chembl_ids = list(dict.fromkeys(
            candidate["chembl_id"] for candidate in candidates
        ))
        profiles, response_metadata = client.drugs(chembl_ids)
        response_version = _open_targets_version(response_metadata)
        if response_version != source_version:
            raise ValueError(
                "Open Targets data version changed during the enrichment batch"
            )
        matched = 0
        not_found = 0
        relationships = 0
        with get_cortellis_session() as session:
            for candidate in candidates:
                profile = profiles.get(candidate["chembl_id"])
                if not profile:
                    not_found += 1
                    _record_state(
                        session,
                        drug_id=candidate["drug_id"],
                        source=OPEN_TARGETS_SOURCE,
                        source_identifier=candidate["chembl_id"],
                        status="not_found",
                        source_version=source_version,
                    )
                    continue
                matched += 1
                relationships += _upsert_open_targets_profile(
                    session,
                    drug_id=candidate["drug_id"],
                    chembl_id=candidate["chembl_id"],
                    profile=profile,
                    source_version=source_version,
                )
                _record_state(
                    session,
                    drug_id=candidate["drug_id"],
                    source=OPEN_TARGETS_SOURCE,
                    source_identifier=candidate["chembl_id"],
                    status="matched",
                    source_version=source_version,
                )
        return {
            "status": "completed",
            "processed": len(candidates),
            "matched": matched,
            "not_found": not_found,
            "relationships_created": relationships,
            "source_version": source_version,
        }
    finally:
        try:
            lock.execute(text(
                "SELECT pg_advisory_unlock(hashtext('onebd_open_targets_enrichment'))"
            ))
        finally:
            lock.close()


def public_drug_enrichment_status() -> dict[str, Any]:
    ensure_public_drug_schema()
    with get_cortellis_session() as session:
        row = session.execute(text("""
            SELECT
                (SELECT COUNT(DISTINCT drug_id) FROM drug_identifiers
                 WHERE identifier_type = 'inchikey') AS drugs_with_inchikey,
                (SELECT COUNT(DISTINCT drug_id) FROM drug_identifiers
                 WHERE identifier_type = 'chembl_id') AS drugs_with_chembl_id,
                (SELECT COUNT(DISTINCT drug_id) FROM public_drug_profiles)
                    AS drugs_with_open_targets_profile,
                (SELECT COUNT(*) FROM public_targets) AS targets,
                (SELECT COUNT(*) FROM public_diseases) AS diseases,
                (SELECT COUNT(*) FROM public_drug_target_links) AS drug_target_links,
                (SELECT COUNT(*) FROM public_drug_disease_links)
                    AS drug_disease_links,
                (SELECT COUNT(*) FROM drug_aliases
                 WHERE source = :chembl_source
                   AND alias_type <> 'chembl_preferred_name')
                    AS chembl_typed_aliases,
                (SELECT COUNT(DISTINCT drug_id) FROM drug_aliases
                 WHERE source = :chembl_source
                   AND alias_type <> 'chembl_preferred_name')
                    AS drugs_with_chembl_typed_aliases,
                (SELECT COUNT(*) FROM drug_aliases
                 WHERE source = :chembl_source
                   AND alias_type IN ('inn', 'inn_french', 'inn_spanish'))
                    AS chembl_inn_aliases,
                (SELECT COUNT(*) FROM drug_aliases
                 WHERE source = :chembl_source
                   AND alias_type = 'development_code')
                    AS chembl_development_codes,
                (SELECT COUNT(*) FROM (
                   SELECT normalized_value
                   FROM drug_aliases
                   WHERE source = :chembl_source
                     AND alias_type <> 'chembl_preferred_name'
                   GROUP BY normalized_value
                   HAVING COUNT(DISTINCT drug_id) > 1
                 ) shared) AS shared_chembl_typed_aliases,
                (SELECT MAX(source_version) FROM drug_chembl_records)
                    AS chembl_version,
                (SELECT MAX(source_version) FROM public_drug_profiles)
                    AS open_targets_version
        """), {"chembl_source": CHEMBL_SOURCE}).mappings().one()
        states = [dict(item) for item in session.execute(text("""
            SELECT source, status, COUNT(*) AS records
            FROM public_drug_source_state
            GROUP BY source, status
            ORDER BY source, status
        """)).mappings().all()]
    result = dict(row)
    result["chembl_coverage_pct"] = round(
        100 * int(row["drugs_with_chembl_id"] or 0)
        / max(1, int(row["drugs_with_inchikey"] or 0)),
        2,
    )
    result["open_targets_coverage_pct"] = round(
        100 * int(row["drugs_with_open_targets_profile"] or 0)
        / max(1, int(row["drugs_with_chembl_id"] or 0)),
        2,
    )
    result["states"] = states
    return result
