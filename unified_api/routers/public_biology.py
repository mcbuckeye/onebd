"""Read-only ChEMBL and Open Targets drug, target, and disease endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from unified_api.services.database import get_cortellis_session
from unified_api.services.europe_pmc_enrichment import ensure_europe_pmc_schema
from unified_api.services.uniprot_enrichment import ensure_public_target_schema


router = APIRouter()


@router.get("/public-biology/targets")
async def list_public_targets(
    query: str | None = None,
    drug_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Search canonical Ensembl targets and optionally require an exact drug link."""
    ensure_public_target_schema()
    filters: list[str] = []
    params: dict[str, object] = {"limit": limit, "offset": offset}
    if query:
        filters.append("(target.approved_symbol ILIKE :query OR "
                       "target.approved_name ILIKE :query OR "
                       "target.ensembl_id ILIKE :query)")
        params["query"] = f"%{query}%"
    if drug_id is not None:
        filters.append("EXISTS (SELECT 1 FROM public_drug_target_links link "
                       "WHERE link.ensembl_id = target.ensembl_id "
                       "AND link.drug_id = :drug_id)")
        params["drug_id"] = drug_id
    where = "WHERE " + " AND ".join(filters) if filters else ""
    with get_cortellis_session() as session:
        total = session.execute(text(f"""
            SELECT COUNT(*) FROM public_targets target {where}
        """), params).scalar_one()
        rows = session.execute(text(f"""
            SELECT target.ensembl_id, target.approved_symbol,
                   target.approved_name, target.biotype, target.protein_ids,
                   target.source, target.source_version,
                   target.first_seen_at, target.last_seen_at,
                   COUNT(DISTINCT link.drug_id) AS linked_drugs,
                   COUNT(DISTINCT link.chembl_id) AS linked_chembl_compounds,
                   COUNT(DISTINCT uniprot.requested_accession)
                       AS uniprot_records
            FROM public_targets target
            LEFT JOIN public_drug_target_links link
              ON link.ensembl_id = target.ensembl_id
            LEFT JOIN public_target_uniprot_records uniprot
              ON uniprot.ensembl_id = target.ensembl_id
            {where}
            GROUP BY target.ensembl_id
            ORDER BY linked_drugs DESC, target.approved_symbol,
                     target.ensembl_id
            LIMIT :limit OFFSET :offset
        """), params).mappings().all()
    return {
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "targets": [dict(row) for row in rows],
    }


@router.get("/public-biology/targets/{ensembl_id}")
async def public_target_detail(ensembl_id: str):
    """Return a canonical target and its exact source-derived drug mechanisms."""
    ensure_public_target_schema()
    ensembl_id = ensembl_id.upper()
    with get_cortellis_session() as session:
        target = session.execute(text("""
            SELECT * FROM public_targets WHERE ensembl_id = :ensembl_id
        """), {"ensembl_id": ensembl_id}).mappings().first()
        if not target:
            raise HTTPException(status_code=404, detail="Public target not found")
        drugs = session.execute(text("""
            SELECT link.drug_id, drug.name_display, link.chembl_id,
                   profile.name AS public_name, link.mechanism_of_action,
                   link.action_type, link.target_name,
                   link.source_references,
                   link.source, link.source_version, profile.source_url
            FROM public_drug_target_links link
            JOIN drugs drug ON drug.id = link.drug_id
            LEFT JOIN public_drug_profiles profile
              ON profile.drug_id = link.drug_id
             AND profile.chembl_id = link.chembl_id
            WHERE link.ensembl_id = :ensembl_id
            ORDER BY drug.name_display, link.chembl_id,
                     link.mechanism_of_action
        """), {"ensembl_id": ensembl_id}).mappings().all()
        uniprot_records = session.execute(text("""
            SELECT requested_accession, primary_accession, uniprot_id,
                   entry_type, reviewed, protein_name, gene_symbol,
                   gene_synonyms, organism_name, organism_taxon_id,
                   function_text, disease_annotations,
                   subcellular_locations, sequence_length,
                   sequence_checksum, source, source_version,
                   source_release_date, source_url,
                   first_seen_at, last_seen_at
            FROM public_target_uniprot_records
            WHERE ensembl_id = :ensembl_id
            ORDER BY requested_accession
        """), {"ensembl_id": ensembl_id}).mappings().all()
    return {
        "target": dict(target),
        "linked_drugs": [dict(row) for row in drugs],
        "uniprot_records": [dict(row) for row in uniprot_records],
    }


@router.get("/public-biology/targets/{ensembl_id}/literature")
async def public_target_literature(
    ensembl_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Return publications linked by exact structured target identifiers."""
    ensure_europe_pmc_schema()
    ensembl_id = ensembl_id.upper()
    with get_cortellis_session() as session:
        target = session.execute(text("""
            SELECT ensembl_id, approved_symbol, approved_name
            FROM public_targets WHERE ensembl_id = :ensembl_id
        """), {"ensembl_id": ensembl_id}).mappings().first()
        if not target:
            raise HTTPException(status_code=404, detail="Public target not found")
        total = session.execute(text("""
            SELECT COUNT(DISTINCT (link.article_source, link.external_id))
            FROM public_target_literature_links link
            WHERE link.ensembl_id = :ensembl_id
        """), {"ensembl_id": ensembl_id}).scalar_one()
        rows = session.execute(text("""
            SELECT publication.article_source, publication.external_id,
                   publication.pmid, publication.pmcid, publication.doi,
                   publication.title, publication.abstract_text,
                   publication.author_string, publication.journal_title,
                   publication.publication_year,
                   publication.first_publication_date,
                   publication.publication_types,
                   publication.mesh_headings, publication.chemicals,
                   publication.cited_by_count, publication.is_open_access,
                   publication.in_europe_pmc, publication.source,
                   publication.source_version, publication.source_url,
                   link.requested_accessions, link.match_methods,
                   link.source_queries
            FROM (
              SELECT article_source, external_id,
                     ARRAY_AGG(DISTINCT requested_accession)
                         AS requested_accessions,
                     ARRAY_AGG(DISTINCT match_method) AS match_methods,
                     ARRAY_AGG(DISTINCT source_query) AS source_queries
              FROM public_target_literature_links
              WHERE ensembl_id = :ensembl_id
              GROUP BY article_source, external_id
            ) link
            JOIN public_literature_records publication
              ON publication.article_source = link.article_source
             AND publication.external_id = link.external_id
            ORDER BY publication.cited_by_count DESC NULLS LAST,
                     publication.first_publication_date DESC NULLS LAST,
                     publication.article_source, publication.external_id
            LIMIT :limit OFFSET :offset
        """), {
            "ensembl_id": ensembl_id,
            "limit": limit,
            "offset": offset,
        }).mappings().all()
    return {
        "target": dict(target),
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "publications": [dict(row) for row in rows],
    }


@router.get("/public-biology/diseases")
async def list_public_diseases(
    query: str | None = None,
    drug_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Search source-defined disease concepts and exact drug indication links."""
    ensure_public_target_schema()
    filters: list[str] = []
    params: dict[str, object] = {"limit": limit, "offset": offset}
    if query:
        filters.append("(disease.name ILIKE :query OR "
                       "disease.disease_id ILIKE :query)")
        params["query"] = f"%{query}%"
    if drug_id is not None:
        filters.append("EXISTS (SELECT 1 FROM public_drug_disease_links link "
                       "WHERE link.disease_id = disease.disease_id "
                       "AND link.drug_id = :drug_id)")
        params["drug_id"] = drug_id
    where = "WHERE " + " AND ".join(filters) if filters else ""
    with get_cortellis_session() as session:
        total = session.execute(text(f"""
            SELECT COUNT(*) FROM public_diseases disease {where}
        """), params).scalar_one()
        rows = session.execute(text(f"""
            SELECT disease.disease_id, disease.name, disease.source,
                   disease.source_version, disease.first_seen_at,
                   disease.last_seen_at,
                   COUNT(DISTINCT link.drug_id) AS linked_drugs,
                   COUNT(DISTINCT link.chembl_id) AS linked_chembl_compounds
            FROM public_diseases disease
            LEFT JOIN public_drug_disease_links link
              ON link.disease_id = disease.disease_id
            {where}
            GROUP BY disease.disease_id
            ORDER BY linked_drugs DESC, disease.name, disease.disease_id
            LIMIT :limit OFFSET :offset
        """), params).mappings().all()
    return {
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "diseases": [dict(row) for row in rows],
    }


@router.get("/public-biology/diseases/{disease_id}")
async def public_disease_detail(disease_id: str):
    """Return a source disease concept and linked drug development stages."""
    ensure_public_target_schema()
    with get_cortellis_session() as session:
        disease = session.execute(text("""
            SELECT * FROM public_diseases WHERE disease_id = :disease_id
        """), {"disease_id": disease_id}).mappings().first()
        if not disease:
            raise HTTPException(status_code=404, detail="Public disease not found")
        drugs = session.execute(text("""
            SELECT link.drug_id, drug.name_display, link.chembl_id,
                   profile.name AS public_name, link.maximum_clinical_stage,
                   link.source_record_id, link.source, link.source_version,
                   profile.source_url
            FROM public_drug_disease_links link
            JOIN drugs drug ON drug.id = link.drug_id
            LEFT JOIN public_drug_profiles profile
              ON profile.drug_id = link.drug_id
             AND profile.chembl_id = link.chembl_id
            WHERE link.disease_id = :disease_id
            ORDER BY drug.name_display, link.chembl_id
        """), {"disease_id": disease_id}).mappings().all()
    return {
        "disease": dict(disease),
        "linked_drugs": [dict(row) for row in drugs],
    }


@router.get("/drugs/{drug_id}/public-biology")
async def drug_public_biology(
    drug_id: int,
    include_raw: bool = Query(default=False),
):
    """Return exact public identifiers, profiles, targets, and indications."""
    ensure_europe_pmc_schema()
    with get_cortellis_session() as session:
        drug = session.execute(text("""
            SELECT id, name_display FROM drugs WHERE id = :drug_id
        """), {"drug_id": drug_id}).mappings().first()
        if not drug:
            raise HTTPException(status_code=404, detail="Drug not found")
        identifiers = session.execute(text("""
            SELECT identifier_type, identifier_value, source,
                   source_reference, evidence, confidence, review_status
            FROM drug_identifiers
            WHERE drug_id = :drug_id
              AND identifier_type IN (
                  'pubchem_cid', 'inchikey', 'connectivity_smiles', 'chembl_id'
              )
            ORDER BY identifier_type, identifier_value
        """), {"drug_id": drug_id}).mappings().all()
        chembl_raw_column = ", record.raw_payload" if include_raw else ""
        chembl_records = session.execute(text(f"""
            SELECT record.chembl_id, record.standard_inchi_key,
                   record.preferred_name, record.molecule_type,
                   record.max_phase, record.first_approval,
                   record.source_version, record.source_url,
                   record.first_seen_at, record.last_seen_at
                   {chembl_raw_column}
            FROM drug_chembl_records record
            WHERE record.drug_id = :drug_id
            ORDER BY record.chembl_id
        """), {"drug_id": drug_id}).mappings().all()
        raw_column = ", profile.raw_payload" if include_raw else ""
        profiles = session.execute(text(f"""
            SELECT profile.chembl_id, profile.name, profile.description,
                   profile.drug_type, profile.maximum_clinical_stage,
                   profile.synonyms, profile.trade_names,
                   profile.cross_references, profile.source,
                   profile.source_version, profile.source_url,
                   profile.first_seen_at, profile.last_seen_at
                   {raw_column}
            FROM public_drug_profiles profile
            WHERE profile.drug_id = :drug_id
            ORDER BY profile.chembl_id
        """), {"drug_id": drug_id}).mappings().all()
        targets = session.execute(text("""
            SELECT target.ensembl_id, target.approved_symbol,
                   target.approved_name, target.biotype, target.protein_ids,
                   link.chembl_id, link.mechanism_of_action,
                   link.action_type, link.target_name,
                   link.source_references,
                   link.source, link.source_version,
                   COALESCE((
                     SELECT jsonb_agg(jsonb_build_object(
                       'requested_accession', record.requested_accession,
                       'primary_accession', record.primary_accession,
                       'uniprot_id', record.uniprot_id,
                       'protein_name', record.protein_name,
                       'gene_symbol', record.gene_symbol,
                       'function_text', record.function_text,
                       'source_version', record.source_version,
                       'source_url', record.source_url
                     ) ORDER BY record.requested_accession)
                     FROM public_target_uniprot_records record
                     WHERE record.ensembl_id = target.ensembl_id
                   ), '[]'::jsonb) AS uniprot_records,
                   (SELECT COUNT(DISTINCT (
                        literature.article_source, literature.external_id
                    ))
                    FROM public_target_literature_links literature
                    WHERE literature.ensembl_id = target.ensembl_id)
                       AS literature_count
            FROM public_drug_target_links link
            JOIN public_targets target
              ON target.ensembl_id = link.ensembl_id
            WHERE link.drug_id = :drug_id
            ORDER BY target.approved_symbol, link.chembl_id,
                     link.mechanism_of_action
        """), {"drug_id": drug_id}).mappings().all()
        diseases = session.execute(text("""
            SELECT disease.disease_id, disease.name, link.chembl_id,
                   link.maximum_clinical_stage, link.source_record_id,
                   link.source, link.source_version
            FROM public_drug_disease_links link
            JOIN public_diseases disease
              ON disease.disease_id = link.disease_id
            WHERE link.drug_id = :drug_id
            ORDER BY disease.name, link.chembl_id
        """), {"drug_id": drug_id}).mappings().all()
    return {
        "drug": dict(drug),
        "identifiers": [dict(row) for row in identifiers],
        "chembl_records": [dict(row) for row in chembl_records],
        "profiles": [dict(row) for row in profiles],
        "targets": [dict(row) for row in targets],
        "diseases": [dict(row) for row in diseases],
    }
