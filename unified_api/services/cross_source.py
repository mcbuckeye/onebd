"""Governed, provenance-preserving search across OneBD source datasets."""

from __future__ import annotations

from datetime import date, datetime, timezone
import time
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from sqlalchemy import text

from unified_api.config import settings
from unified_api.services.database import (
    get_cortellis_session,
    get_edgar_source_session,
)


ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
FederatedDataset = Literal[
    "deals",
    "assets",
    "companies",
    "clinical_trials",
    "edgar",
    "contracts",
    "literature",
    "targets",
    "diseases",
    "proteins",
]
ALL_FEDERATED_DATASETS: tuple[FederatedDataset, ...] = (
    "deals",
    "assets",
    "companies",
    "clinical_trials",
    "edgar",
    "contracts",
    "literature",
    "targets",
    "diseases",
    "proteins",
)
DATASET_POLICY_GROUP = {
    "deals": "cortellis_deals",
    "contracts": "cortellis_deals",
    "assets": "integrated_drugs",
    "companies": "integrated_companies",
    "clinical_trials": "clinicaltrials_gov",
    "edgar": "sec_edgar",
    "literature": "public_biology",
    "targets": "public_biology",
    "diseases": "public_biology",
    "proteins": "public_biology",
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class PagedSearch(StrictModel):
    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=10000)


class EdgarContentSearchRequest(PagedSearch):
    query: str = Field(min_length=3, max_length=300)
    company: ShortText | None = None
    cik: str | None = Field(default=None, max_length=20)
    forms: list[ShortText] = Field(default_factory=list, max_length=20)
    date_from: date | None = None
    date_to: date | None = None

    @model_validator(mode="after")
    def validate_dates(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from cannot be after date_to")
        if self.cik:
            self.cik = self.cik.strip().zfill(10)
        self.forms = list(dict.fromkeys(value.strip() for value in self.forms))
        return self


class ContractContentSearchRequest(PagedSearch):
    query: str = Field(min_length=3, max_length=300)
    deal_id: int | None = Field(default=None, ge=1)
    company_id: int | None = Field(default=None, ge=1)
    drug_id: int | None = Field(default=None, ge=1)


class LiteratureSearchRequest(PagedSearch):
    query: str | None = Field(default=None, min_length=2, max_length=300)
    target_id: ShortText | None = None
    drug_id: int | None = Field(default=None, ge=1)
    company_id: int | None = Field(default=None, ge=1)
    publication_year_gte: int | None = Field(default=None, ge=1800, le=2200)
    publication_year_lte: int | None = Field(default=None, ge=1800, le=2200)
    open_access: bool | None = None

    @model_validator(mode="after")
    def require_filter(self):
        if (
            not self.query
            and not self.target_id
            and self.drug_id is None
            and self.company_id is None
        ):
            raise ValueError(
                "literature search requires query, target_id, drug_id, or company_id"
            )
        if (
            self.publication_year_gte
            and self.publication_year_lte
            and self.publication_year_gte > self.publication_year_lte
        ):
            raise ValueError("publication_year_gte cannot exceed publication_year_lte")
        return self


class ProteinSearchRequest(PagedSearch):
    query: str | None = Field(default=None, min_length=2, max_length=300)
    target_id: ShortText | None = None
    drug_id: int | None = Field(default=None, ge=1)
    company_id: int | None = Field(default=None, ge=1)
    reviewed: bool | None = None
    organism_taxon_id: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def require_filter(self):
        if (
            not self.query
            and not self.target_id
            and self.drug_id is None
            and self.company_id is None
        ):
            raise ValueError(
                "protein search requires query, target_id, drug_id, or company_id"
            )
        return self


class ClinicalTrialSearchRequest(PagedSearch):
    query: str | None = Field(default=None, min_length=2, max_length=300)
    statuses: list[ShortText] = Field(default_factory=list, max_length=20)
    phases: list[ShortText] = Field(default_factory=list, max_length=20)
    conditions: list[ShortText] = Field(default_factory=list, max_length=30)
    sponsor: ShortText | None = None
    company_id: int | None = Field(default=None, ge=1)
    drug_id: int | None = Field(default=None, ge=1)
    indication_id: int | None = Field(default=None, ge=1)
    start_date_gte: date | None = None
    start_date_lte: date | None = None
    primary_completion_gte: date | None = None
    primary_completion_lte: date | None = None
    has_results: bool | None = None

    @model_validator(mode="after")
    def normalize(self):
        self.statuses = list(
            dict.fromkeys(value.strip().upper() for value in self.statuses)
        )
        self.phases = list(dict.fromkeys(value.strip().upper() for value in self.phases))
        self.conditions = list(
            dict.fromkeys(value.strip() for value in self.conditions)
        )
        for lower, upper, label in (
            (self.start_date_gte, self.start_date_lte, "start_date"),
            (
                self.primary_completion_gte,
                self.primary_completion_lte,
                "primary_completion",
            ),
        ):
            if lower and upper and lower > upper:
                raise ValueError(f"{label}_gte cannot be after {label}_lte")
        return self


class FederatedSearchRequest(StrictModel):
    query: str = Field(min_length=2, max_length=300)
    datasets: list[FederatedDataset] = Field(
        default_factory=lambda: list(ALL_FEDERATED_DATASETS),
        min_length=1,
        max_length=len(ALL_FEDERATED_DATASETS),
    )
    company_id: int | None = Field(default=None, ge=1)
    drug_id: int | None = Field(default=None, ge=1)
    cik: str | None = Field(default=None, max_length=20)
    date_from: date | None = None
    date_to: date | None = None
    limit_per_dataset: int = Field(default=10, ge=1, le=25)

    @model_validator(mode="after")
    def normalize(self):
        self.datasets = list(dict.fromkeys(self.datasets))
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from cannot be after date_to")
        if self.cik:
            self.cik = self.cik.strip().zfill(10)
        return self


def _page(items: list[dict[str, Any]], limit: int, offset: int) -> dict[str, Any]:
    has_more = len(items) > limit
    return {
        "items": items[:limit],
        "limit": limit,
        "offset": offset,
        "has_more": has_more,
        "next_offset": offset + limit if has_more else None,
    }


def _rows(result) -> list[dict[str, Any]]:
    return [dict(row) for row in result.mappings().all()]


def search_edgar_content(
    session,
    request: EdgarContentSearchRequest,
    *,
    timeout_ms: int = 20000,
) -> dict[str, Any]:
    conditions = [
        "to_tsvector('english', chunk.text) @@ "
        "websearch_to_tsquery('english', :query)"
    ]
    params: dict[str, Any] = {
        "query": request.query,
        "limit": request.limit + 1,
        "offset": request.offset,
        "candidate_limit": min(
            10000,
            max(
                settings.edgar_fulltext_candidate_limit,
                (request.offset + request.limit + 1) * 10,
            ),
        ),
    }
    if request.company:
        conditions.append(
            "(company.name ILIKE :company OR company.ticker ILIKE :company)"
        )
        params["company"] = f"%{request.company}%"
    if request.cik:
        conditions.append("LPAD(company.cik, 10, '0')=:cik")
        params["cik"] = request.cik
    if request.forms:
        conditions.append("COALESCE(document.subtype, document.doc_type)=ANY(:forms)")
        params["forms"] = request.forms
    if request.date_from:
        conditions.append("raw.filing_date >= :date_from")
        params["date_from"] = request.date_from
    if request.date_to:
        conditions.append("raw.filing_date < :date_to + INTERVAL '1 day'")
        params["date_to"] = request.date_to

    session.execute(text(f"SET LOCAL statement_timeout = {max(1, timeout_ms)}"))
    items = _rows(
        session.execute(
            text(f"""
                WITH candidates AS MATERIALIZED (
                    SELECT chunk.id AS chunk_id, chunk.document_id,
                           chunk.section, chunk.text,
                           to_tsvector('english', chunk.text) AS search_vector,
                           document.accession_no,
                           COALESCE(document.subtype, document.doc_type) AS form,
                           document.title, raw.filing_date, raw.url AS source_url,
                           company.name AS company_name, company.ticker,
                           LPAD(company.cik, 10, '0') AS cik
                    FROM chunks chunk
                    JOIN documents document ON document.id=chunk.document_id
                    JOIN raw_documents raw ON raw.id=document.raw_document_id
                    JOIN companies company ON company.id=raw.company_id
                    WHERE {' AND '.join(conditions)}
                    LIMIT :candidate_limit
                )
                SELECT chunk_id, document_id, section,
                       ts_headline(
                         'english', text,
                         websearch_to_tsquery('english', :query),
                         'MaxWords=60, MinWords=20, ShortWord=2'
                       ) AS excerpt,
                       ts_rank(search_vector,
                         websearch_to_tsquery('english', :query)) AS score,
                       accession_no, form, title, filing_date, source_url,
                       company_name, ticker, cik,
                       'sec_edgar'::text AS dataset,
                       'SEC EDGAR filing chunk'::text AS attribution
                FROM candidates
                ORDER BY score DESC, chunk_id
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
    )
    return {
        "query": request.query,
        "dataset": "sec_edgar",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **_page(items, request.limit, request.offset),
    }


def search_contract_content(
    session,
    request: ContractContentSearchRequest,
    *,
    timeout_ms: int = 20000,
) -> dict[str, Any]:
    conditions = [
        "content.content_tsvector @@ websearch_to_tsquery('english', :query)"
    ]
    params: dict[str, Any] = {
        "query": request.query,
        "limit": request.limit + 1,
        "offset": request.offset,
    }
    if request.deal_id:
        conditions.append("content.deal_id=:deal_id")
        params["deal_id"] = request.deal_id
    if request.company_id:
        conditions.append(
            "EXISTS (SELECT 1 FROM deal_companies company_link WHERE "
            "company_link.deal_id=content.deal_id "
            "AND company_link.company_id=:company_id)"
        )
        params["company_id"] = request.company_id
    if request.drug_id:
        conditions.append(
            "EXISTS (SELECT 1 FROM deal_drugs drug_link WHERE "
            "drug_link.deal_id=content.deal_id AND drug_link.drug_id=:drug_id)"
        )
        params["drug_id"] = request.drug_id
    session.execute(text(f"SET LOCAL statement_timeout = {max(1, timeout_ms)}"))
    items = _rows(
        session.execute(
            text(f"""
                SELECT content.id AS content_id, content.contract_id,
                       content.deal_id, deal.title AS deal_title,
                       ts_headline(
                         'english', content.content,
                         websearch_to_tsquery('english', :query),
                         'MaxWords=70, MinWords=25, ShortWord=2'
                       ) AS excerpt,
                       ts_rank(content.content_tsvector,
                         websearch_to_tsquery('english', :query)) AS score,
                       content.word_count, content.indexed_at,
                       'cortellis_contract'::text AS dataset,
                       'indexed contract text linked to deal'::text AS attribution
                FROM contract_content content
                JOIN deals deal ON deal.id=content.deal_id
                WHERE {' AND '.join(conditions)}
                ORDER BY score DESC, content.id
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
    )
    return {
        "query": request.query,
        "dataset": "cortellis_contracts",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **_page(items, request.limit, request.offset),
    }


def search_literature(
    session,
    request: LiteratureSearchRequest,
    *,
    timeout_ms: int = 20000,
) -> dict[str, Any]:
    conditions = ["TRUE"]
    params: dict[str, Any] = {
        "limit": request.limit + 1,
        "offset": request.offset,
    }
    score = "0::real"
    if request.query:
        conditions.append(
            "to_tsvector('english', COALESCE(publication.title, '') || ' ' || "
            "COALESCE(publication.abstract_text, '')) @@ "
            "websearch_to_tsquery('english', :query)"
        )
        params["query"] = request.query
        score = (
            "ts_rank(to_tsvector('english', COALESCE(publication.title, '') || "
            "' ' || COALESCE(publication.abstract_text, '')), "
            "websearch_to_tsquery('english', :query))"
        )
    if request.target_id:
        conditions.append(
            "EXISTS (SELECT 1 FROM public_target_literature_links link WHERE "
            "link.article_source=publication.article_source "
            "AND link.external_id=publication.external_id "
            "AND link.ensembl_id=:target_id)"
        )
        params["target_id"] = request.target_id.upper()
    if request.drug_id:
        conditions.append(
            "EXISTS (SELECT 1 FROM public_target_literature_links link "
            "JOIN public_drug_target_links drug_target "
            "ON drug_target.ensembl_id=link.ensembl_id "
            "WHERE link.article_source=publication.article_source "
            "AND link.external_id=publication.external_id "
            "AND drug_target.drug_id=:drug_id)"
        )
        params["drug_id"] = request.drug_id
    if request.company_id:
        conditions.append(
            "EXISTS (SELECT 1 FROM public_target_literature_links link "
            "JOIN public_drug_target_links drug_target "
            "ON drug_target.ensembl_id=link.ensembl_id "
            "JOIN deal_drugs drug_deal ON drug_deal.drug_id=drug_target.drug_id "
            "JOIN deal_companies company_deal "
            "ON company_deal.deal_id=drug_deal.deal_id "
            "WHERE link.article_source=publication.article_source "
            "AND link.external_id=publication.external_id "
            "AND company_deal.company_id=:company_id)"
        )
        params["company_id"] = request.company_id
    if request.publication_year_gte:
        conditions.append("publication.publication_year >= :year_gte")
        params["year_gte"] = request.publication_year_gte
    if request.publication_year_lte:
        conditions.append("publication.publication_year <= :year_lte")
        params["year_lte"] = request.publication_year_lte
    if request.open_access is not None:
        conditions.append("publication.is_open_access=:open_access")
        params["open_access"] = request.open_access

    session.execute(text(f"SET LOCAL statement_timeout = {max(1, timeout_ms)}"))
    items = _rows(
        session.execute(
            text(f"""
                SELECT publication.article_source, publication.external_id,
                       publication.pmid, publication.pmcid, publication.doi,
                       publication.title,
                       LEFT(publication.abstract_text, 1200) AS abstract_excerpt,
                       publication.author_string, publication.journal_title,
                       publication.publication_year,
                       publication.first_publication_date,
                       publication.publication_types,
                       publication.cited_by_count,
                       publication.is_open_access, publication.source,
                       publication.source_version, publication.source_url,
                       {score} AS score,
                       COALESCE((SELECT jsonb_agg(DISTINCT link.ensembl_id)
                         FROM public_target_literature_links link
                         WHERE link.article_source=publication.article_source
                           AND link.external_id=publication.external_id),
                         '[]'::jsonb) AS linked_targets,
                       'target/protein query provenance'::text AS attribution
                FROM public_literature_records publication
                WHERE {' AND '.join(conditions)}
                ORDER BY score DESC, publication.cited_by_count DESC NULLS LAST,
                         publication.first_publication_date DESC NULLS LAST,
                         publication.article_source, publication.external_id
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
    )
    return {
        "query": request.query,
        "dataset": "europe_pmc",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **_page(items, request.limit, request.offset),
    }


def search_proteins(
    session,
    request: ProteinSearchRequest,
    *,
    timeout_ms: int = 20000,
) -> dict[str, Any]:
    conditions = ["TRUE"]
    params: dict[str, Any] = {
        "limit": request.limit + 1,
        "offset": request.offset,
    }
    score = "0::real"
    if request.query:
        params["query"] = request.query
        conditions.append(
            "(protein.primary_accession ILIKE '%' || :query || '%' OR "
            "protein.requested_accession ILIKE '%' || :query || '%' OR "
            "protein.uniprot_id ILIKE '%' || :query || '%' OR "
            "protein.gene_symbol ILIKE '%' || :query || '%' OR "
            "to_tsvector('english', COALESCE(protein.protein_name, '') || ' ' || "
            "COALESCE(protein.function_text, '')) @@ "
            "websearch_to_tsquery('english', :query))"
        )
        score = (
            "ts_rank(to_tsvector('english', COALESCE(protein.protein_name, '') || "
            "' ' || COALESCE(protein.function_text, '')), "
            "websearch_to_tsquery('english', :query))"
        )
    if request.target_id:
        conditions.append("protein.ensembl_id=:target_id")
        params["target_id"] = request.target_id.upper()
    if request.drug_id:
        conditions.append(
            "EXISTS (SELECT 1 FROM public_drug_target_links link WHERE "
            "link.ensembl_id=protein.ensembl_id AND link.drug_id=:drug_id)"
        )
        params["drug_id"] = request.drug_id
    if request.company_id:
        conditions.append(
            "EXISTS (SELECT 1 FROM public_drug_target_links target_link "
            "JOIN deal_drugs drug_deal ON drug_deal.drug_id=target_link.drug_id "
            "JOIN deal_companies company_deal "
            "ON company_deal.deal_id=drug_deal.deal_id "
            "WHERE target_link.ensembl_id=protein.ensembl_id "
            "AND company_deal.company_id=:company_id)"
        )
        params["company_id"] = request.company_id
    if request.reviewed is not None:
        conditions.append("protein.reviewed=:reviewed")
        params["reviewed"] = request.reviewed
    if request.organism_taxon_id:
        conditions.append("protein.organism_taxon_id=:organism_taxon_id")
        params["organism_taxon_id"] = request.organism_taxon_id

    session.execute(text(f"SET LOCAL statement_timeout = {max(1, timeout_ms)}"))
    items = _rows(
        session.execute(
            text(f"""
                SELECT protein.ensembl_id, target.approved_symbol,
                       target.approved_name, protein.requested_accession,
                       protein.primary_accession, protein.uniprot_id,
                       protein.entry_type, protein.reviewed,
                       protein.protein_name, protein.gene_symbol,
                       protein.gene_synonyms, protein.organism_name,
                       protein.organism_taxon_id,
                       LEFT(protein.function_text, 1500) AS function_excerpt,
                       protein.disease_annotations,
                       protein.subcellular_locations, protein.sequence_length,
                       protein.source, protein.source_version,
                       protein.source_release_date, protein.source_url,
                       {score} AS score,
                       'exact Ensembl-to-UniProt accession link'::text AS attribution
                FROM public_target_uniprot_records protein
                JOIN public_targets target
                  ON target.ensembl_id=protein.ensembl_id
                WHERE {' AND '.join(conditions)}
                ORDER BY score DESC, protein.reviewed DESC,
                         protein.primary_accession
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
    )
    return {
        "query": request.query,
        "dataset": "uniprot",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **_page(items, request.limit, request.offset),
    }


def search_clinical_trials(
    session,
    request: ClinicalTrialSearchRequest,
    *,
    timeout_ms: int = 20000,
) -> dict[str, Any]:
    conditions = ["TRUE"]
    params: dict[str, Any] = {
        "limit": request.limit + 1,
        "offset": request.offset,
    }
    score = "0::real"
    if request.query:
        params["query"] = request.query
        document = (
            "COALESCE(trial.brief_title, '') || ' ' || "
            "COALESCE(trial.official_title, '') || ' ' || "
            "COALESCE(trial.lead_sponsor_name, '') || ' ' || "
            "trial.conditions::text || ' ' || trial.interventions::text"
        )
        conditions.append(
            f"to_tsvector('english', {document}) @@ "
            "websearch_to_tsquery('english', :query)"
        )
        score = (
            f"ts_rank(to_tsvector('english', {document}), "
            "websearch_to_tsquery('english', :query))"
        )
    if request.statuses:
        conditions.append("trial.overall_status=ANY(:statuses)")
        params["statuses"] = request.statuses
    if request.phases:
        conditions.append("trial.phases ?| CAST(:phases AS text[])")
        params["phases"] = request.phases
    for index, condition in enumerate(request.conditions):
        key = f"condition_{index}"
        conditions.append(f"trial.conditions::text ILIKE :{key}")
        params[key] = f"%{condition}%"
    if request.sponsor:
        conditions.append("trial.lead_sponsor_name ILIKE :sponsor")
        params["sponsor"] = f"%{request.sponsor}%"
    if request.company_id:
        conditions.append(
            "EXISTS (SELECT 1 FROM clinical_trial_companies link WHERE "
            "link.nct_id=trial.nct_id AND link.company_id=:company_id)"
        )
        params["company_id"] = request.company_id
    if request.drug_id:
        conditions.append(
            "EXISTS (SELECT 1 FROM clinical_trial_drugs link WHERE "
            "link.nct_id=trial.nct_id AND link.drug_id=:drug_id)"
        )
        params["drug_id"] = request.drug_id
    if request.indication_id:
        conditions.append(
            "EXISTS (SELECT 1 FROM clinical_trial_indications link WHERE "
            "link.nct_id=trial.nct_id AND link.indication_id=:indication_id)"
        )
        params["indication_id"] = request.indication_id
    for field, value, operator, key in (
        ("trial.start_date", request.start_date_gte, ">=", "start_gte"),
        ("trial.start_date", request.start_date_lte, "<=", "start_lte"),
        (
            "trial.primary_completion_date",
            request.primary_completion_gte,
            ">=",
            "completion_gte",
        ),
        (
            "trial.primary_completion_date",
            request.primary_completion_lte,
            "<=",
            "completion_lte",
        ),
    ):
        if value:
            conditions.append(f"{field} {operator} :{key}")
            params[key] = value
    if request.has_results is not None:
        conditions.append("trial.has_results=:has_results")
        params["has_results"] = request.has_results

    session.execute(text(f"SET LOCAL statement_timeout = {max(1, timeout_ms)}"))
    items = _rows(
        session.execute(
            text(f"""
                SELECT trial.nct_id, trial.brief_title, trial.official_title,
                       trial.overall_status, trial.why_stopped, trial.phases,
                       trial.study_type, trial.enrollment, trial.start_date,
                       trial.primary_completion_date, trial.completion_date,
                       trial.last_update_posted, trial.lead_sponsor_name,
                       trial.lead_sponsor_class, trial.collaborators,
                       trial.conditions, trial.interventions, trial.has_results,
                       trial.source, trial.source_url, {score} AS score,
                       COALESCE((SELECT jsonb_agg(jsonb_build_object(
                         'drug_id', link.drug_id,
                         'intervention_name', link.intervention_name,
                         'match_method', link.match_method,
                         'confidence', link.confidence))
                         FROM clinical_trial_drugs link
                         WHERE link.nct_id=trial.nct_id), '[]'::jsonb)
                         AS linked_drugs,
                       COALESCE((SELECT jsonb_agg(jsonb_build_object(
                         'company_id', link.company_id,
                         'organization_name', link.organization_name,
                         'organization_role', link.organization_role,
                         'match_method', link.match_method,
                         'confidence', link.confidence))
                         FROM clinical_trial_companies link
                         WHERE link.nct_id=trial.nct_id), '[]'::jsonb)
                         AS linked_companies,
                       'ClinicalTrials.gov structured record'::text AS attribution
                FROM clinical_trials trial
                WHERE {' AND '.join(conditions)}
                ORDER BY score DESC, trial.last_update_posted DESC NULLS LAST,
                         trial.nct_id
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
    )
    return {
        "query": request.query,
        "dataset": "clinicaltrials_gov",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **_page(items, request.limit, request.offset),
    }


def _simple_group(
    session,
    dataset: FederatedDataset,
    request: FederatedSearchRequest,
) -> dict[str, Any]:
    query = f"%{request.query}%"
    limit = request.limit_per_dataset
    common = {"query": query, "limit": limit}
    if dataset == "deals":
        filters = ["(deal.title ILIKE :query OR deal.summary ILIKE :query)"]
        if request.company_id:
            filters.append(
                "EXISTS (SELECT 1 FROM deal_companies link WHERE "
                "link.deal_id=deal.id AND link.company_id=:company_id)"
            )
            common["company_id"] = request.company_id
        if request.drug_id:
            filters.append(
                "EXISTS (SELECT 1 FROM deal_drugs link WHERE "
                "link.deal_id=deal.id AND link.drug_id=:drug_id)"
            )
            common["drug_id"] = request.drug_id
        if request.date_from:
            filters.append("deal.date_start >= :date_from")
            common["date_from"] = request.date_from
        if request.date_to:
            filters.append("deal.date_start < :date_to + INTERVAL '1 day'")
            common["date_to"] = request.date_to
        sql = f"""
            SELECT deal.id, deal.title, deal.deal_type, deal.status,
                   deal.date_start, deal.date_change_last,
                   LEFT(deal.summary, 700) AS summary_excerpt,
                   'cortellis_deals'::text AS source,
                   'deal record'::text AS attribution
            FROM deals deal WHERE {' AND '.join(filters)}
            ORDER BY deal.date_change_last DESC NULLS LAST, deal.id
            LIMIT :limit
        """
    elif dataset == "assets":
        filters = [
            "(drug.name_display ILIKE :query OR EXISTS (SELECT 1 FROM "
            "drug_aliases alias WHERE alias.drug_id=drug.id "
            "AND alias.alias_value ILIKE :query))"
        ]
        if request.drug_id:
            filters.append("drug.id=:drug_id")
            common["drug_id"] = request.drug_id
        if request.company_id:
            filters.append(
                "EXISTS (SELECT 1 FROM deal_drugs dl JOIN deal_companies cl "
                "ON cl.deal_id=dl.deal_id WHERE dl.drug_id=drug.id "
                "AND cl.company_id=:company_id)"
            )
            common["company_id"] = request.company_id
        sql = f"""
            SELECT drug.id, drug.name_display, drug.phase_highest_now,
                   COUNT(DISTINCT link.deal_id)::int AS deal_count,
                   'integrated_drugs'::text AS source,
                   'deal asset with source-attributed public enrichment'::text
                     AS attribution
            FROM drugs drug LEFT JOIN deal_drugs link ON link.drug_id=drug.id
            WHERE {' AND '.join(filters)} GROUP BY drug.id
            ORDER BY deal_count DESC, drug.name_display, drug.id LIMIT :limit
        """
    elif dataset == "companies":
        filters = [
            "(company.name ILIKE :query OR company.ticker ILIKE :query OR "
            "EXISTS (SELECT 1 FROM company_identifiers identifier WHERE "
            "identifier.company_id=company.id "
            "AND identifier.identifier_value ILIKE :query))"
        ]
        if request.company_id:
            filters.append("company.id=:company_id")
            common["company_id"] = request.company_id
        sql = f"""
            SELECT company.id, company.name, company.company_type,
                   company.hq_location, company.cik, company.ticker,
                   COUNT(DISTINCT link.deal_id)::int AS deal_count,
                   'integrated_companies'::text AS source,
                   'canonical company with verified identifiers'::text
                     AS attribution
            FROM companies company
            LEFT JOIN deal_companies link ON link.company_id=company.id
            WHERE {' AND '.join(filters)} GROUP BY company.id
            ORDER BY deal_count DESC, company.name, company.id LIMIT :limit
        """
    elif dataset == "targets":
        filters = [
            "(target.approved_symbol ILIKE :query OR "
            "target.approved_name ILIKE :query OR target.ensembl_id ILIKE :query)"
        ]
        if request.drug_id:
            filters.append(
                "EXISTS (SELECT 1 FROM public_drug_target_links link WHERE "
                "link.ensembl_id=target.ensembl_id AND link.drug_id=:drug_id)"
            )
            common["drug_id"] = request.drug_id
        if request.company_id:
            filters.append(
                "EXISTS (SELECT 1 FROM public_drug_target_links target_link "
                "JOIN deal_drugs drug_deal "
                "ON drug_deal.drug_id=target_link.drug_id "
                "JOIN deal_companies company_deal "
                "ON company_deal.deal_id=drug_deal.deal_id "
                "WHERE target_link.ensembl_id=target.ensembl_id "
                "AND company_deal.company_id=:company_id)"
            )
            common["company_id"] = request.company_id
        sql = f"""
            SELECT target.ensembl_id, target.approved_symbol,
                   target.approved_name, target.biotype,
                   COUNT(DISTINCT link.drug_id)::int AS linked_drugs,
                   target.source, target.source_version,
                   'public target concept'::text AS attribution
            FROM public_targets target
            LEFT JOIN public_drug_target_links link
              ON link.ensembl_id=target.ensembl_id
            WHERE {' AND '.join(filters)} GROUP BY target.ensembl_id
            ORDER BY linked_drugs DESC, target.approved_symbol LIMIT :limit
        """
    elif dataset == "diseases":
        filters = [
            "(disease.name ILIKE :query OR disease.disease_id ILIKE :query)"
        ]
        if request.drug_id:
            filters.append(
                "EXISTS (SELECT 1 FROM public_drug_disease_links link WHERE "
                "link.disease_id=disease.disease_id AND link.drug_id=:drug_id)"
            )
            common["drug_id"] = request.drug_id
        if request.company_id:
            filters.append(
                "EXISTS (SELECT 1 FROM public_drug_disease_links disease_link "
                "JOIN deal_drugs drug_deal "
                "ON drug_deal.drug_id=disease_link.drug_id "
                "JOIN deal_companies company_deal "
                "ON company_deal.deal_id=drug_deal.deal_id "
                "WHERE disease_link.disease_id=disease.disease_id "
                "AND company_deal.company_id=:company_id)"
            )
            common["company_id"] = request.company_id
        sql = f"""
            SELECT disease.disease_id, disease.name,
                   COUNT(DISTINCT link.drug_id)::int AS linked_drugs,
                   disease.source, disease.source_version,
                   'public disease concept'::text AS attribution
            FROM public_diseases disease
            LEFT JOIN public_drug_disease_links link
              ON link.disease_id=disease.disease_id
            WHERE {' AND '.join(filters)} GROUP BY disease.disease_id
            ORDER BY linked_drugs DESC, disease.name LIMIT :limit
        """
    else:
        raise ValueError(f"Unsupported simple dataset: {dataset}")
    return {
        "dataset": dataset,
        "items": _rows(session.execute(text(sql), common)),
    }


def run_federated_search(request: FederatedSearchRequest) -> dict[str, Any]:
    """Run bounded source-specific queries and keep their result grains separate."""
    started = time.perf_counter()
    groups: list[dict[str, Any]] = []

    def remaining_ms() -> int:
        return max(1, 25000 - int((time.perf_counter() - started) * 1000))

    cortellis_datasets = [name for name in request.datasets if name != "edgar"]
    if cortellis_datasets:
        with get_cortellis_session() as session:
            session.execute(text("SET LOCAL statement_timeout = 20000"))
            for dataset in cortellis_datasets:
                session.execute(
                    text(f"SET LOCAL statement_timeout = {remaining_ms()}")
                )
                if dataset in {"deals", "assets", "companies", "targets", "diseases"}:
                    group = _simple_group(session, dataset, request)
                elif dataset == "contracts":
                    result = search_contract_content(
                        session,
                        ContractContentSearchRequest(
                            query=request.query,
                            company_id=request.company_id,
                            drug_id=request.drug_id,
                            limit=request.limit_per_dataset,
                        ),
                        timeout_ms=remaining_ms(),
                    )
                    group = {"dataset": dataset, "items": result["items"]}
                elif dataset == "clinical_trials":
                    result = search_clinical_trials(
                        session,
                        ClinicalTrialSearchRequest(
                            query=request.query,
                            company_id=request.company_id,
                            drug_id=request.drug_id,
                            start_date_gte=request.date_from,
                            start_date_lte=request.date_to,
                            limit=request.limit_per_dataset,
                        ),
                        timeout_ms=remaining_ms(),
                    )
                    group = {"dataset": dataset, "items": result["items"]}
                elif dataset == "literature":
                    result = search_literature(
                        session,
                        LiteratureSearchRequest(
                            query=request.query,
                            drug_id=request.drug_id,
                            company_id=request.company_id,
                            limit=request.limit_per_dataset,
                        ),
                        timeout_ms=remaining_ms(),
                    )
                    group = {"dataset": dataset, "items": result["items"]}
                elif dataset == "proteins":
                    result = search_proteins(
                        session,
                        ProteinSearchRequest(
                            query=request.query,
                            drug_id=request.drug_id,
                            company_id=request.company_id,
                            limit=request.limit_per_dataset,
                        ),
                        timeout_ms=remaining_ms(),
                    )
                    group = {"dataset": dataset, "items": result["items"]}
                else:
                    continue
                group["returned"] = len(group["items"])
                group["policy_dataset"] = DATASET_POLICY_GROUP[dataset]
                groups.append(group)

    if "edgar" in request.datasets:
        cik = request.cik
        if not cik and request.company_id:
            with get_cortellis_session() as session:
                cik = session.execute(
                    text("""
                        SELECT COALESCE(company.cik, (
                          SELECT identifier.normalized_value
                          FROM company_identifiers identifier
                          WHERE identifier.company_id=company.id
                            AND LOWER(identifier.identifier_type)='cik'
                          ORDER BY identifier.confidence DESC LIMIT 1
                        )) FROM companies company WHERE company.id=:company_id
                    """),
                    {"company_id": request.company_id},
                ).scalar()
        if request.company_id and not cik:
            groups.append({
                "dataset": "edgar",
                "policy_dataset": "sec_edgar",
                "returned": 0,
                "items": [],
                "limitation": (
                    "EDGAR was not searched because the selected company has "
                    "no exact normalized CIK."
                ),
            })
        else:
            with get_edgar_source_session() as session:
                result = search_edgar_content(
                    session,
                    EdgarContentSearchRequest(
                        query=request.query,
                        cik=cik,
                        date_from=request.date_from,
                        date_to=request.date_to,
                        limit=request.limit_per_dataset,
                    ),
                    timeout_ms=remaining_ms(),
                )
            groups.append({
                "dataset": "edgar",
                "policy_dataset": "sec_edgar",
                "returned": len(result["items"]),
                "items": result["items"],
            })

    by_name = {group["dataset"]: group for group in groups}
    ordered = [by_name[name] for name in request.datasets if name in by_name]
    return {
        "query": request.query,
        "requested_datasets": request.datasets,
        "limit_per_dataset": request.limit_per_dataset,
        "groups": ordered,
        "returned": sum(group["returned"] for group in ordered),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "limitations": [
            "Results remain grouped by source and record grain; relevance scores are not comparable across datasets.",
            "Cross-source entity filters use exact curated links where available and do not imply ownership, rights, or causality.",
        ],
    }
