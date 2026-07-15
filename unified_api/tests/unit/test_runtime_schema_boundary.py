"""Live processes must not execute application schema DDL."""

from unittest.mock import MagicMock

from src import cortellis_archive, cortellis_catalog
from unified_api.services import (
    clinical_trials,
    cortellis_contract_sync,
    financial_terms,
    pubchem_enrichment,
)


def test_pre_migrated_runtime_skips_cached_and_session_schema_ddl(monkeypatch):
    monkeypatch.setenv("ONEBD_RUNTIME_SCHEMA_MIGRATED", "true")
    monkeypatch.setattr(clinical_trials, "_clinical_trials_schema_ready", False)
    monkeypatch.setattr(pubchem_enrichment, "_pubchem_schema_ready", False)
    monkeypatch.setattr(cortellis_contract_sync, "_contract_scan_schema_ready", False)
    monkeypatch.setattr(cortellis_archive, "_expanded_archive_schema_ready", False)
    session = MagicMock()

    clinical_trials.ensure_clinical_trials_schema()
    pubchem_enrichment.ensure_pubchem_schema()
    cortellis_contract_sync.ensure_contract_scan_schema()
    cortellis_archive.ensure_expanded_archive_schema(session)
    cortellis_catalog.ensure_catalog_exclusion_schema(session)
    cortellis_catalog.ensure_catalog_proof_schema(session)
    financial_terms.ensure_financial_term_schema(session)

    session.execute.assert_not_called()
    assert clinical_trials._clinical_trials_schema_ready is True
    assert pubchem_enrichment._pubchem_schema_ready is True
    assert cortellis_contract_sync._contract_scan_schema_ready is True
    assert cortellis_archive._expanded_archive_schema_ready is True
