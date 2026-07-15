"""Evidence-bounded company and asset dossiers across integrated sources."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from unified_api.services.database import (
    get_cortellis_session,
    get_edgar_source_session,
)


def _rows(result) -> list[dict[str, Any]]:
    return [dict(row) for row in result.mappings().all()]


def _first(result) -> dict[str, Any] | None:
    row = result.mappings().first()
    return dict(row) if row else None


def build_company_dossier(
    company_id: int,
    *,
    disabled_datasets: set[str] | None = None,
) -> dict[str, Any] | None:
    disabled = disabled_datasets or set()
    with get_cortellis_session() as session:
        session.execute(text("SET LOCAL statement_timeout = 20000"))
        company = _first(
            session.execute(
                text("""
                    SELECT company.id, company.name, company.company_type,
                           company.hq_location, company.cik, company.ticker,
                           COALESCE((SELECT jsonb_agg(jsonb_build_object(
                             'type', identifier.identifier_type,
                             'value', identifier.identifier_value,
                             'source', identifier.source,
                             'source_reference', identifier.source_reference,
                             'confidence', identifier.confidence,
                             'review_status', identifier.review_status)
                             ORDER BY identifier.identifier_type,
                                      identifier.identifier_value)
                             FROM company_identifiers identifier
                             WHERE identifier.company_id=company.id),
                             '[]'::jsonb) AS identifiers
                    FROM companies company WHERE company.id=:company_id
                """),
                {"company_id": company_id},
            )
        )
        if company is None:
            return None

        deals: list[dict[str, Any]] = []
        assets: list[dict[str, Any]] = []
        if "cortellis_deals" not in disabled:
            deals = _rows(
                session.execute(
                    text("""
                        SELECT deal.id, deal.title, deal.deal_type,
                               deal.agreement_type, deal.transaction_type,
                               deal.status, deal.date_start,
                               deal.date_change_last, company_link.role,
                               LEFT(deal.summary, 700) AS summary_excerpt,
                               COALESCE((SELECT jsonb_agg(jsonb_build_object(
                                 'id', drug.id, 'name', drug.name_display,
                                 'phase', drug.phase_highest_now)
                                 ORDER BY drug.name_display)
                                 FROM deal_drugs drug_link JOIN drugs drug
                                   ON drug.id=drug_link.drug_id
                                 WHERE drug_link.deal_id=deal.id),
                                 '[]'::jsonb) AS assets,
                               COALESCE((SELECT jsonb_agg(jsonb_build_object(
                                 'source_id', source.source_id,
                                 'source_type', source.source_type)
                                 ORDER BY source.source_type, source.source_id)
                                 FROM cortellis_deal_sources source
                                 WHERE source.deal_id=deal.id
                                   AND source.is_current=TRUE),
                                 '[]'::jsonb) AS source_citations,
                               'exact company-to-deal link'::text
                                 AS relationship_basis
                        FROM deal_companies company_link
                        JOIN deals deal ON deal.id=company_link.deal_id
                        WHERE company_link.company_id=:company_id
                        ORDER BY deal.date_change_last DESC NULLS LAST,
                                 deal.id DESC
                        LIMIT 50
                    """),
                    {"company_id": company_id},
                )
            )
            assets = _rows(
                session.execute(
                    text("""
                        SELECT drug.id, drug.name_display,
                               drug.phase_highest_start,
                               drug.phase_highest_now,
                               COUNT(DISTINCT drug_link.deal_id)::int
                                 AS linked_deal_count,
                               ARRAY_AGG(DISTINCT drug_link.deal_id
                                 ORDER BY drug_link.deal_id) AS deal_ids,
                               ARRAY_AGG(DISTINCT company_link.role
                                 ORDER BY company_link.role) AS company_roles,
                               'shared deal link; ownership not established'::text
                                 AS relationship_basis,
                               false AS ownership_or_control_established
                        FROM deal_companies company_link
                        JOIN deal_drugs drug_link
                          ON drug_link.deal_id=company_link.deal_id
                        JOIN drugs drug ON drug.id=drug_link.drug_id
                        WHERE company_link.company_id=:company_id
                        GROUP BY drug.id
                        ORDER BY linked_deal_count DESC, drug.name_display,
                                 drug.id
                        LIMIT 100
                    """),
                    {"company_id": company_id},
                )
            )

        trials: list[dict[str, Any]] = []
        if "clinicaltrials_gov" not in disabled:
            trials = _rows(
                session.execute(
                    text("""
                        SELECT trial.nct_id, trial.brief_title,
                               trial.overall_status, trial.phases,
                               trial.start_date,
                               trial.primary_completion_date,
                               trial.last_update_posted,
                               trial.lead_sponsor_name, trial.conditions,
                               trial.interventions, trial.has_results,
                               trial.source_url, link.organization_name,
                               link.organization_role, link.match_method,
                               link.confidence,
                               'normalized-exact structured organization link'::text
                                 AS relationship_basis
                        FROM clinical_trial_companies link
                        JOIN clinical_trials trial ON trial.nct_id=link.nct_id
                        WHERE link.company_id=:company_id
                        ORDER BY trial.last_update_posted DESC NULLS LAST,
                                 trial.nct_id
                        LIMIT 50
                    """),
                    {"company_id": company_id},
                )
            )

        targets: list[dict[str, Any]] = []
        diseases: list[dict[str, Any]] = []
        literature: list[dict[str, Any]] = []
        if "public_biology" not in disabled:
            targets = _rows(
                session.execute(
                    text("""
                        SELECT target.ensembl_id, target.approved_symbol,
                               target.approved_name,
                               COUNT(DISTINCT drug_link.drug_id)::int
                                 AS linked_asset_count,
                               ARRAY_AGG(DISTINCT drug_link.drug_id
                                 ORDER BY drug_link.drug_id) AS drug_ids,
                               ARRAY_AGG(DISTINCT target_link.action_type)
                                 FILTER (WHERE target_link.action_type IS NOT NULL)
                                 AS action_types,
                               target.source, target.source_version,
                               'public target linked to asset in a company deal'::text
                                 AS relationship_basis
                        FROM deal_companies company_link
                        JOIN deal_drugs drug_link
                          ON drug_link.deal_id=company_link.deal_id
                        JOIN public_drug_target_links target_link
                          ON target_link.drug_id=drug_link.drug_id
                        JOIN public_targets target
                          ON target.ensembl_id=target_link.ensembl_id
                        WHERE company_link.company_id=:company_id
                        GROUP BY target.ensembl_id
                        ORDER BY linked_asset_count DESC,
                                 target.approved_symbol
                        LIMIT 100
                    """),
                    {"company_id": company_id},
                )
            )
            diseases = _rows(
                session.execute(
                    text("""
                        SELECT disease.disease_id, disease.name,
                               COUNT(DISTINCT drug_link.drug_id)::int
                                 AS linked_asset_count,
                               ARRAY_AGG(DISTINCT drug_link.drug_id
                                 ORDER BY drug_link.drug_id) AS drug_ids,
                               disease.source, disease.source_version,
                               'public disease linked to asset in a company deal'::text
                                 AS relationship_basis
                        FROM deal_companies company_link
                        JOIN deal_drugs drug_link
                          ON drug_link.deal_id=company_link.deal_id
                        JOIN public_drug_disease_links disease_link
                          ON disease_link.drug_id=drug_link.drug_id
                        JOIN public_diseases disease
                          ON disease.disease_id=disease_link.disease_id
                        WHERE company_link.company_id=:company_id
                        GROUP BY disease.disease_id
                        ORDER BY linked_asset_count DESC, disease.name
                        LIMIT 100
                    """),
                    {"company_id": company_id},
                )
            )
            literature = _rows(
                session.execute(
                    text("""
                        SELECT DISTINCT publication.article_source,
                               publication.external_id, publication.pmid,
                               publication.pmcid, publication.doi,
                               publication.title, publication.journal_title,
                               publication.publication_year,
                               publication.cited_by_count,
                               publication.is_open_access,
                               publication.source, publication.source_url,
                               'publication linked through target of asset in company deal'::text
                                 AS relationship_basis
                        FROM deal_companies company_link
                        JOIN deal_drugs drug_link
                          ON drug_link.deal_id=company_link.deal_id
                        JOIN public_drug_target_links target_link
                          ON target_link.drug_id=drug_link.drug_id
                        JOIN public_target_literature_links literature_link
                          ON literature_link.ensembl_id=target_link.ensembl_id
                        JOIN public_literature_records publication
                          ON publication.article_source=literature_link.article_source
                         AND publication.external_id=literature_link.external_id
                        WHERE company_link.company_id=:company_id
                        ORDER BY publication.cited_by_count DESC NULLS LAST,
                                 publication.publication_year DESC NULLS LAST
                        LIMIT 50
                    """),
                    {"company_id": company_id},
                )
            )

    filings: list[dict[str, Any]] = []
    cik = str(company.get("cik") or "").strip().zfill(10)
    if cik != "0000000000" and "sec_edgar" not in disabled:
        with get_edgar_source_session() as session:
            session.execute(text("SET LOCAL statement_timeout = 20000"))
            filings = _rows(
                session.execute(
                    text("""
                        SELECT document.id, document.accession_no,
                               COALESCE(document.subtype, document.doc_type)
                                 AS form,
                               document.title, raw.filing_date,
                               raw.url AS source_url, edgar_company.name,
                               edgar_company.ticker,
                               LPAD(edgar_company.cik, 10, '0') AS cik,
                               'exact normalized CIK'::text
                                 AS relationship_basis
                        FROM documents document
                        JOIN raw_documents raw
                          ON raw.id=document.raw_document_id
                        JOIN companies edgar_company
                          ON edgar_company.id=raw.company_id
                        WHERE LPAD(edgar_company.cik, 10, '0')=:cik
                        ORDER BY raw.filing_date DESC NULLS LAST,
                                 document.id DESC
                        LIMIT 50
                    """),
                    {"cik": cik},
                )
            )

    return {
        "entity": "company",
        "company": company,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "blocks": {
            "cortellis_deals": deals,
            "deal_linked_assets": assets,
            "clinical_trials": trials,
            "public_targets": targets,
            "public_diseases": diseases,
            "literature": literature,
            "sec_filings": filings,
        },
        "disabled_datasets": sorted(disabled),
        "limitations": [
            "A company and asset sharing a deal does not establish ownership or control.",
            "Public biology and literature are linked through deal-referenced assets and targets; they are not company-authored evidence.",
            "SEC filings use an exact normalized CIK and may discuss topics unrelated to a specific deal or asset.",
        ],
    }


def build_asset_dossier(
    drug_id: int,
    *,
    disabled_datasets: set[str] | None = None,
) -> dict[str, Any] | None:
    disabled = disabled_datasets or set()
    with get_cortellis_session() as session:
        session.execute(text("SET LOCAL statement_timeout = 20000"))
        asset = _first(
            session.execute(
                text("""
                    SELECT drug.id, drug.name_display,
                           drug.phase_highest_start, drug.phase_highest_now,
                           COALESCE((SELECT jsonb_agg(jsonb_build_object(
                             'value', alias.alias_value,
                             'type', alias.alias_type, 'source', alias.source,
                             'confidence', alias.confidence,
                             'review_status', alias.review_status)
                             ORDER BY alias.alias_value)
                             FROM drug_aliases alias
                             WHERE alias.drug_id=drug.id), '[]'::jsonb)
                             AS aliases,
                           COALESCE((SELECT jsonb_agg(jsonb_build_object(
                             'type', identifier.identifier_type,
                             'value', identifier.identifier_value,
                             'source', identifier.source,
                             'source_reference', identifier.source_reference,
                             'confidence', identifier.confidence,
                             'review_status', identifier.review_status)
                             ORDER BY identifier.identifier_type,
                                      identifier.identifier_value)
                             FROM drug_identifiers identifier
                             WHERE identifier.drug_id=drug.id), '[]'::jsonb)
                             AS identifiers
                    FROM drugs drug WHERE drug.id=:drug_id
                """),
                {"drug_id": drug_id},
            )
        )
        if asset is None:
            return None

        deals: list[dict[str, Any]] = []
        if "cortellis_deals" not in disabled:
            deals = _rows(
                session.execute(
                    text("""
                        SELECT deal.id, deal.title, deal.deal_type,
                               deal.agreement_type, deal.transaction_type,
                               deal.status, deal.date_start,
                               deal.date_change_last,
                               LEFT(deal.summary, 700) AS summary_excerpt,
                               COALESCE((SELECT jsonb_agg(jsonb_build_object(
                                 'id', company.id, 'name', company.name,
                                 'role', company_link.role)
                                 ORDER BY company_link.role, company.name)
                                 FROM deal_companies company_link
                                 JOIN companies company
                                   ON company.id=company_link.company_id
                                 WHERE company_link.deal_id=deal.id),
                                 '[]'::jsonb) AS companies,
                               'exact deal-to-asset link'::text
                                 AS relationship_basis
                        FROM deal_drugs drug_link
                        JOIN deals deal ON deal.id=drug_link.deal_id
                        WHERE drug_link.drug_id=:drug_id
                        ORDER BY deal.date_change_last DESC NULLS LAST,
                                 deal.id DESC
                        LIMIT 100
                    """),
                    {"drug_id": drug_id},
                )
            )

        trials: list[dict[str, Any]] = []
        if "clinicaltrials_gov" not in disabled:
            trials = _rows(
                session.execute(
                    text("""
                        SELECT trial.nct_id, trial.brief_title,
                               trial.overall_status, trial.phases,
                               trial.start_date,
                               trial.primary_completion_date,
                               trial.last_update_posted,
                               trial.lead_sponsor_name, trial.conditions,
                               trial.interventions, trial.has_results,
                               trial.source_url, link.intervention_name,
                               link.matched_alias, link.match_method,
                               link.confidence,
                               'normalized-exact intervention alias link'::text
                                 AS relationship_basis
                        FROM clinical_trial_drugs link
                        JOIN clinical_trials trial ON trial.nct_id=link.nct_id
                        WHERE link.drug_id=:drug_id
                        ORDER BY trial.last_update_posted DESC NULLS LAST,
                                 trial.nct_id
                        LIMIT 100
                    """),
                    {"drug_id": drug_id},
                )
            )

        profiles: list[dict[str, Any]] = []
        targets: list[dict[str, Any]] = []
        diseases: list[dict[str, Any]] = []
        proteins: list[dict[str, Any]] = []
        literature: list[dict[str, Any]] = []
        if "public_biology" not in disabled:
            profiles = _rows(
                session.execute(
                    text("""
                        SELECT profile.chembl_id, profile.name,
                               profile.description, profile.drug_type,
                               profile.maximum_clinical_stage,
                               profile.synonyms, profile.trade_names,
                               profile.cross_references, profile.source,
                               profile.source_version, profile.source_url,
                               chembl.standard_inchi_key,
                               chembl.preferred_name,
                               chembl.molecule_type, chembl.max_phase,
                               chembl.first_approval
                        FROM public_drug_profiles profile
                        LEFT JOIN drug_chembl_records chembl
                          ON chembl.drug_id=profile.drug_id
                         AND chembl.chembl_id=profile.chembl_id
                        WHERE profile.drug_id=:drug_id
                        ORDER BY profile.chembl_id
                    """),
                    {"drug_id": drug_id},
                )
            )
            targets = _rows(
                session.execute(
                    text("""
                        SELECT target.ensembl_id, target.approved_symbol,
                               target.approved_name, target.biotype,
                               link.chembl_id, link.mechanism_of_action,
                               link.action_type, link.target_name,
                               link.source_references, link.source,
                               link.source_version,
                               'exact public drug-target mechanism link'::text
                                 AS relationship_basis
                        FROM public_drug_target_links link
                        JOIN public_targets target
                          ON target.ensembl_id=link.ensembl_id
                        WHERE link.drug_id=:drug_id
                        ORDER BY target.approved_symbol, link.chembl_id
                    """),
                    {"drug_id": drug_id},
                )
            )
            diseases = _rows(
                session.execute(
                    text("""
                        SELECT disease.disease_id, disease.name,
                               link.chembl_id,
                               link.maximum_clinical_stage,
                               link.source_record_id, link.source,
                               link.source_version,
                               'exact public drug-disease link'::text
                                 AS relationship_basis
                        FROM public_drug_disease_links link
                        JOIN public_diseases disease
                          ON disease.disease_id=link.disease_id
                        WHERE link.drug_id=:drug_id
                        ORDER BY disease.name, link.chembl_id
                    """),
                    {"drug_id": drug_id},
                )
            )
            proteins = _rows(
                session.execute(
                    text("""
                        SELECT DISTINCT protein.ensembl_id,
                               protein.requested_accession,
                               protein.primary_accession, protein.uniprot_id,
                               protein.reviewed, protein.protein_name,
                               protein.gene_symbol, protein.organism_name,
                               protein.function_text,
                               protein.disease_annotations,
                               protein.source, protein.source_version,
                               protein.source_url,
                               'drug target to exact UniProt accession link'::text
                                 AS relationship_basis
                        FROM public_drug_target_links target_link
                        JOIN public_target_uniprot_records protein
                          ON protein.ensembl_id=target_link.ensembl_id
                        WHERE target_link.drug_id=:drug_id
                        ORDER BY protein.ensembl_id,
                                 protein.primary_accession
                    """),
                    {"drug_id": drug_id},
                )
            )
            literature = _rows(
                session.execute(
                    text("""
                        SELECT DISTINCT publication.article_source,
                               publication.external_id, publication.pmid,
                               publication.pmcid, publication.doi,
                               publication.title, publication.journal_title,
                               publication.publication_year,
                               publication.cited_by_count,
                               publication.is_open_access,
                               publication.source, publication.source_url,
                               literature_link.ensembl_id,
                               'publication linked through an exact drug target'::text
                                 AS relationship_basis
                        FROM public_drug_target_links target_link
                        JOIN public_target_literature_links literature_link
                          ON literature_link.ensembl_id=target_link.ensembl_id
                        JOIN public_literature_records publication
                          ON publication.article_source=literature_link.article_source
                         AND publication.external_id=literature_link.external_id
                        WHERE target_link.drug_id=:drug_id
                        ORDER BY publication.cited_by_count DESC NULLS LAST,
                                 publication.publication_year DESC NULLS LAST
                        LIMIT 100
                    """),
                    {"drug_id": drug_id},
                )
            )

        related_ciks = list(
            session.execute(
                text("""
                    SELECT DISTINCT LPAD(company.cik, 10, '0')
                    FROM deal_drugs drug_link
                    JOIN deal_companies company_link
                      ON company_link.deal_id=drug_link.deal_id
                    JOIN companies company ON company.id=company_link.company_id
                    WHERE drug_link.drug_id=:drug_id
                      AND NULLIF(BTRIM(company.cik), '') IS NOT NULL
                    ORDER BY 1 LIMIT 50
                """),
                {"drug_id": drug_id},
            ).scalars()
        )

    filings: list[dict[str, Any]] = []
    if related_ciks and "sec_edgar" not in disabled:
        with get_edgar_source_session() as session:
            session.execute(text("SET LOCAL statement_timeout = 20000"))
            filings = _rows(
                session.execute(
                    text("""
                        SELECT document.id, document.accession_no,
                               COALESCE(document.subtype, document.doc_type)
                                 AS form,
                               document.title, raw.filing_date,
                               raw.url AS source_url, company.name,
                               company.ticker,
                               LPAD(company.cik, 10, '0') AS cik,
                               'filing company participates in an asset-linked deal; filing is not asset-specific'::text
                                 AS relationship_basis
                        FROM documents document
                        JOIN raw_documents raw
                          ON raw.id=document.raw_document_id
                        JOIN companies company ON company.id=raw.company_id
                        WHERE LPAD(company.cik, 10, '0')=ANY(:ciks)
                        ORDER BY raw.filing_date DESC NULLS LAST,
                                 document.id DESC
                        LIMIT 50
                    """),
                    {"ciks": related_ciks},
                )
            )

    return {
        "entity": "asset",
        "asset": asset,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "blocks": {
            "cortellis_deals": deals,
            "clinical_trials": trials,
            "public_drug_profiles": profiles,
            "public_targets": targets,
            "public_diseases": diseases,
            "uniprot_proteins": proteins,
            "literature": literature,
            "related_company_sec_filings": filings,
        },
        "disabled_datasets": sorted(disabled),
        "limitations": [
            "Deal participation by a company does not establish asset ownership or current rights.",
            "Trial intervention links use normalized exact aliases but can still represent combination partners or comparators.",
            "Related SEC filings are selected through companies participating in asset-linked deals and are not evidence about the asset unless their text says so.",
        ],
    }
