"""Versioned, read-only, policy-governed data API for colleagues and MCP."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from starlette.concurrency import run_in_threadpool
import structlog

from unified_api.services.api_credentials import (
    DataPrincipal,
    get_data_access_policy,
    require_data_access,
)
from unified_api.services.advanced_search import (
    AdvancedSearchRequest,
    search_assets as run_advanced_asset_search,
    search_deals as run_advanced_deal_search,
)
from unified_api.services.database import (
    get_cortellis_engine,
    get_cortellis_session,
    get_edgar_session,
)
from unified_api.services.entity_counts import get_entity_counts
from unified_api.services.company_asset_intelligence import (
    company_asset_intelligence,
)
from unified_api.services.finance_parser import FINANCE_PARSER_VERSION
from unified_api.services.search_guard import (
    SearchBusy,
    SearchRateLimited,
    advanced_search_guard,
)
from unified_api.services.cross_source import (
    DATASET_POLICY_GROUP,
    ClinicalTrialSearchRequest,
    ContractContentSearchRequest,
    EdgarContentSearchRequest,
    FederatedSearchRequest,
    LiteratureSearchRequest,
    ProteinSearchRequest,
    run_federated_search,
    search_clinical_trials as run_clinical_trial_search,
    search_contract_content as run_contract_content_search,
    search_edgar_content as run_edgar_content_search,
    search_literature as run_literature_search,
    search_proteins as run_protein_search,
)
from unified_api.services.cross_source_dossiers import (
    build_asset_dossier,
    build_company_dossier,
)


router = APIRouter(prefix="/v1", tags=["Governed Data API"])
logger = structlog.get_logger(__name__)


SOURCE_CATALOG = [
    {
        "id": "cortellis_deals",
        "name": "Cortellis Deals API",
        "kind": "commercial",
        "license_note": (
            "Licensed Cortellis Deals content. Redistribution and permitted users "
            "are governed by the organization's Clarivate agreement. This label is "
            "advisory; owner policy controls technical enforcement."
        ),
        "scope": (
            "Deals plus companies, assets, indications, mechanisms, technologies, "
            "territories, finance, timelines, patents, contract metadata, and source "
            "citations embedded in or linked from deal responses."
        ),
        "not_in_scope": (
            "The separately licensed Cortellis Drugs, Companies, Sources, Patents, "
            "and Clinical Trials product datasets are not demonstrated entitlements."
        ),
        "documentation_url": "https://developer.clarivate.com/apis/cortellis-np-drugs-api",
    },
    {
        "id": "sec_edgar",
        "name": "SEC EDGAR",
        "kind": "public_government",
        "license_note": "Free public access; SEC fair-access policies apply.",
        "scope": "Filings, filing text, chunks, extracted deal entities and terms.",
        "documentation_url": (
            "https://www.sec.gov/search-filings/edgar-search-assistance/"
            "accessing-edgar-data"
        ),
    },
    {
        "id": "clinicaltrials_gov",
        "name": "ClinicalTrials.gov API v2",
        "kind": "public_government",
        "license_note": (
            "Available at no charge; attribution, currency, processing-date, and "
            "modification disclosures are required by the source terms."
        ),
        "scope": (
            "Protocol, sponsor, phase, status history, endpoints, enrollment, dates, "
            "results, interventions, conditions, collaborators, and locations."
        ),
        "documentation_url": "https://clinicaltrials.gov/about-site/terms-conditions",
    },
    {
        "id": "pubchem",
        "name": "PubChem",
        "kind": "public_mixed_provenance",
        "license_note": (
            "Free to use, but contributed records can carry source-specific rights; "
            "retain PubChem provenance and consult the contributing source."
        ),
        "scope": "Exact-name CID, InChIKey, connectivity SMILES, and public titles.",
        "documentation_url": "https://pubchem.ncbi.nlm.nih.gov/docs/downloads",
    },
    {
        "id": "chembl",
        "name": "ChEMBL",
        "kind": "open_data",
        "license_note": "CC BY-SA 3.0; attribution and share-alike apply.",
        "scope": (
            "Structure-confirmed ChEMBL identifiers, preferred names, typed INNs, "
            "national names, regulatory names, and development codes."
        ),
        "documentation_url": (
            "https://chembl.gitbook.io/chembl-interface-documentation/"
            "frequently-asked-questions/general-questions"
        ),
    },
    {
        "id": "open_targets",
        "name": "Open Targets Platform",
        "kind": "open_data",
        "license_note": "Platform data is CC0 1.0; upstream rights can still apply.",
        "scope": "Drug profiles, target mechanisms, diseases, and development stages.",
        "documentation_url": "https://platform-docs.opentargets.org/licence",
    },
    {
        "id": "uniprot",
        "name": "UniProt",
        "kind": "open_data",
        "license_note": "Copyrightable database content is CC BY 4.0.",
        "scope": (
            "Reviewed protein identifiers, names, genes, function, disease, location, "
            "organism, and sequence metadata for exact target accessions."
        ),
        "documentation_url": "https://www.uniprot.org/help/license",
    },
    {
        "id": "europe_pmc",
        "name": "Europe PMC",
        "kind": "public_mixed_provenance",
        "license_note": (
            "Metadata is broadly accessible; article reuse depends on each article's "
            "copyright/license. OneBD retains metadata, not a blanket content license."
        ),
        "scope": "Target-linked publication metadata and exact structured citations.",
        "documentation_url": "https://europepmc.org/Help",
    },
    {
        "id": "gleif",
        "name": "GLEIF Global LEI Index",
        "kind": "open_data",
        "license_note": "LEI and relationship data are CC0 1.0.",
        "scope": "Verified LEIs and source-confirmed direct/ultimate parent records.",
        "documentation_url": "https://www.gleif.org/en/meta/lei-data-terms-of-use",
    },
    {
        "id": "wikidata",
        "name": "Wikidata",
        "kind": "open_data",
        "license_note": "Structured data is CC0.",
        "scope": "Reviewable official domains matched through exact LEIs.",
        "documentation_url": "https://www.wikidata.org/wiki/Wikidata:Copyright",
    },
]


def _page(rows: list[dict[str, Any]], limit: int, cursor_field: str) -> dict[str, Any]:
    has_more = len(rows) > limit
    items = rows[:limit]
    return {
        "items": items,
        "limit": limit,
        "has_more": has_more,
        "next_cursor": items[-1][cursor_field] if has_more and items else None,
    }


@router.get("/catalog")
async def data_catalog(
    _principal: DataPrincipal = Depends(require_data_access("catalog:read", "catalog")),
):
    """Return live inventory counts, provenance, and advisory license metadata."""
    with get_cortellis_session() as session:
        cortellis = dict(
            session.execute(
                text("""
            SELECT
              (SELECT COUNT(*) FROM deals) AS deals,
              (SELECT COUNT(*) FROM companies) AS deal_embedded_companies,
              (SELECT COUNT(*) FROM drugs) AS deal_embedded_drugs,
              (SELECT COUNT(*) FROM indications) AS deal_embedded_indications,
              (SELECT COUNT(*) FROM actions) AS deal_embedded_actions,
              (SELECT COUNT(*) FROM technologies) AS deal_embedded_technologies,
              (SELECT COUNT(*) FROM patents) AS deal_embedded_patents,
              (SELECT COUNT(*) FROM deal_timeline_events) AS deal_timeline_events,
              (SELECT COUNT(*) FROM deal_contracts) AS contract_metadata,
              (SELECT COUNT(*) FROM contract_content) AS searchable_contracts,
              (SELECT COUNT(*) FROM contract_chunks) AS contract_chunks,
              (SELECT COUNT(*) FROM deal_financial_terms
               WHERE parser_version=:finance_parser_version)
                AS normalized_financial_terms,
              (SELECT COUNT(*) FROM cortellis_expanded_response_history)
                AS expanded_response_versions,
              (SELECT COUNT(DISTINCT deal_id)
               FROM cortellis_expanded_response_history)
                AS deals_with_expanded_response,
              (SELECT COUNT(*) FROM cortellis_deal_source_response_history)
                AS deal_source_responses,
              (SELECT COUNT(DISTINCT deal_id)
               FROM cortellis_deal_source_response_history)
                AS deals_with_source_response,
              (SELECT COUNT(*) FROM cortellis_deal_sources)
                AS deal_source_citations,
              (SELECT COUNT(*) FROM clinical_trials) AS clinical_trials,
              (SELECT COUNT(*) FROM drug_identifiers) AS drug_identifiers,
              (SELECT COUNT(*) FROM public_drug_profiles) AS public_drug_profiles,
              (SELECT COUNT(*) FROM public_targets) AS public_targets,
              (SELECT COUNT(*) FROM public_diseases) AS public_diseases,
              (SELECT COUNT(*) FROM public_drug_target_links) AS drug_target_links,
              (SELECT COUNT(*) FROM public_drug_disease_links) AS drug_disease_links,
              (SELECT COUNT(*) FROM public_target_uniprot_records)
                AS uniprot_target_records,
              (SELECT COUNT(*) FROM public_literature_records)
                AS literature_records,
              (SELECT COUNT(*) FROM company_identifiers) AS company_identifiers,
              (SELECT COUNT(*) FROM cortellis_catalog_exclusions)
                AS preserved_local_only_deals,
              (SELECT retrievable_total FROM cortellis_catalog_proof WHERE id=1)
                AS retrievable_remote_deals,
              (SELECT numeric_id_min FROM cortellis_catalog_proof WHERE id=1)
                AS numeric_id_min,
              (SELECT numeric_id_max FROM cortellis_catalog_proof WHERE id=1)
                AS numeric_id_max,
              (SELECT advertised_total FROM cortellis_catalog_proof WHERE id=1)
                AS advertised_total,
              (SELECT verified_at FROM cortellis_catalog_proof WHERE id=1)
                AS catalog_verified_at,
              (SELECT COUNT(*) FROM cortellis_contract_scan_state)
                AS contract_scan_states
        """),
                {
                    "finance_parser_version": FINANCE_PARSER_VERSION,
                },
            )
            .mappings()
            .one()
        )
    with get_edgar_session() as session:
        edgar = dict(
            session.execute(
                text("""
            SELECT
              (SELECT COUNT(*) FROM documents) AS documents,
              (SELECT COUNT(*) FROM doc_text) AS documents_with_text,
              (SELECT COUNT(*) FROM chunks) AS chunks,
              (SELECT COUNT(*) FROM companies) AS companies,
              (SELECT COUNT(*) FROM deals) AS extracted_deals,
              (SELECT COUNT(*) FROM deal_terms) AS extracted_deal_terms
        """)
            )
            .mappings()
            .one()
        )
    minimum_id = cortellis["numeric_id_min"]
    maximum_id = cortellis["numeric_id_max"]
    membership_method = (
        "bounded requests exhaustively tested every integer ID from "
        f"{minimum_id:,}-{maximum_id:,}"
        if minimum_id is not None and maximum_id is not None
        else "no accepted exhaustive proof is currently stored"
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "license_metadata_is_advisory": True,
        "technical_access_is_owner_controlled": True,
        "cortellis_completeness": {
            "credential_surface": "legacy Cortellis Deals API",
            "retrievable_remote_deals": int(cortellis["retrievable_remote_deals"] or 0),
            "local_deals": int(cortellis["deals"]),
            "remote_deals_missing_locally": max(
                0,
                int(cortellis["retrievable_remote_deals"] or 0)
                - (
                    int(cortellis["deals"])
                    - int(cortellis["preserved_local_only_deals"] or 0)
                ),
            ),
            "preserved_local_only_deals": int(
                cortellis["preserved_local_only_deals"] or 0
            ),
            "advertised_search_total": cortellis["advertised_total"],
            "catalog_verified_at": cortellis["catalog_verified_at"],
            "membership_method": membership_method,
            "expanded_and_source_scan_complete": bool(
                cortellis["deals_with_expanded_response"]
                == cortellis["retrievable_remote_deals"]
                == cortellis["deals_with_source_response"]
            ),
            "contract_metadata_scan_complete": bool(
                cortellis["contract_scan_states"] == cortellis["deals"]
            ),
        },
        "counts": {"cortellis_database": cortellis, "edgar_database": edgar},
        "sources": SOURCE_CATALOG,
    }


@router.get("/deals")
async def list_deals(
    after_id: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    query: str | None = Query(default=None, max_length=200),
    company_id: int | None = None,
    drug_id: int | None = None,
    indication_id: int | None = None,
    _principal: DataPrincipal = Depends(
        require_data_access("deals:read", "cortellis_deals")
    ),
):
    """Cursor-page normalized Cortellis deal summaries."""
    filters = ["deal.id > :after_id"]
    params: dict[str, Any] = {"after_id": after_id, "limit": limit + 1}
    if query:
        filters.append("(deal.title ILIKE :query OR deal.summary ILIKE :query)")
        params["query"] = f"%{query}%"
    if company_id is not None:
        filters.append(
            "EXISTS (SELECT 1 FROM deal_companies link WHERE "
            "link.deal_id=deal.id AND link.company_id=:company_id)"
        )
        params["company_id"] = company_id
    if drug_id is not None:
        filters.append(
            "EXISTS (SELECT 1 FROM deal_drugs link WHERE "
            "link.deal_id=deal.id AND link.drug_id=:drug_id)"
        )
        params["drug_id"] = drug_id
    if indication_id is not None:
        filters.append(
            "EXISTS (SELECT 1 FROM deal_indications link WHERE "
            "link.deal_id=deal.id AND link.indication_id=:indication_id)"
        )
        params["indication_id"] = indication_id
    with get_cortellis_session() as session:
        rows = (
            session.execute(
                text(f"""
            SELECT deal.id, deal.title, deal.deal_type, deal.status,
                   deal.date_start, deal.date_end, deal.date_change_last,
                   deal.agreement_type, deal.asset_type, deal.transaction_type,
                   deal.phase_highest_start, deal.phase_highest_now,
                   finance.total_paid_amount, finance.total_paid_currency,
                   finance.total_projected_current_amount,
                   finance.total_projected_current_currency
            FROM deals deal
            LEFT JOIN deal_finance_summary finance ON finance.deal_id=deal.id
            WHERE {" AND ".join(filters)}
            ORDER BY deal.id
            LIMIT :limit
        """),
                params,
            )
            .mappings()
            .all()
        )
    return _page([dict(row) for row in rows], limit, "id")


def _public_biology_allowed() -> bool:
    policy = get_data_access_policy()
    return "public_biology" not in set(policy.get("disabled_datasets") or [])


@router.get("/counts")
def entity_counts(
    _principal: DataPrincipal = Depends(
        require_data_access("deals:read", "cortellis_deals")
    ),
):
    """Return cached exact counts without running enriched search queries."""
    with get_cortellis_session() as session:
        return get_entity_counts(session)


def _disabled_datasets() -> set[str]:
    return set(get_data_access_policy().get("disabled_datasets") or [])


def _assert_federated_datasets_enabled(request: FederatedSearchRequest) -> None:
    disabled = _disabled_datasets()
    blocked = sorted({
        DATASET_POLICY_GROUP[dataset]
        for dataset in request.datasets
        if DATASET_POLICY_GROUP[dataset] in disabled
    })
    if blocked:
        raise HTTPException(
            status_code=403,
            detail="Datasets disabled by owner policy: " + ", ".join(blocked),
        )


async def _run_guarded_source_query(worker, principal: DataPrincipal):
    def guarded():
        with advanced_search_guard(principal):
            return worker()

    try:
        return await run_in_threadpool(guarded)
    except SearchRateLimited as exc:
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": "60"},
        ) from exc
    except SearchBusy as exc:
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": "5"},
        ) from exc
    except DBAPIError as exc:
        code = getattr(exc.orig, "pgcode", None) or getattr(
            exc.orig, "sqlstate", None
        )
        if code == "57014":
            raise HTTPException(
                status_code=504,
                detail="Cross-source query exceeded its execution budget",
            ) from exc
        raise HTTPException(
            status_code=503,
            detail="A source database is temporarily unavailable",
        ) from exc


@router.post("/edgar/search")
async def governed_edgar_search(
    request: EdgarContentSearchRequest,
    principal: DataPrincipal = Depends(
        require_data_access("sources:read", "sec_edgar")
    ),
):
    """Full-text SEC filing search with company, form, CIK, and date filters."""

    def worker():
        with get_edgar_session() as session:
            return run_edgar_content_search(session, request)

    return await _run_guarded_source_query(worker, principal)


@router.post("/contracts/search")
async def governed_contract_search(
    request: ContractContentSearchRequest,
    principal: DataPrincipal = Depends(
        require_data_access("deals:read", "cortellis_deals")
    ),
):
    """Search indexed Cortellis contract text with exact entity filters."""

    def worker():
        with get_cortellis_session() as session:
            return run_contract_content_search(session, request)

    return await _run_guarded_source_query(worker, principal)


@router.post("/literature/search")
async def governed_literature_search(
    request: LiteratureSearchRequest,
    principal: DataPrincipal = Depends(
        require_data_access("biology:read", "public_biology")
    ),
):
    """Search Europe PMC records and exact target/drug evidence links."""

    def worker():
        with get_cortellis_session() as session:
            return run_literature_search(session, request)

    return await _run_guarded_source_query(worker, principal)


@router.post("/biology/proteins/search")
async def governed_protein_search(
    request: ProteinSearchRequest,
    principal: DataPrincipal = Depends(
        require_data_access("biology:read", "public_biology")
    ),
):
    """Search exact Ensembl-to-UniProt protein records."""

    def worker():
        with get_cortellis_session() as session:
            return run_protein_search(session, request)

    return await _run_guarded_source_query(worker, principal)


@router.post("/clinical-trials/search")
async def governed_clinical_trial_search(
    request: ClinicalTrialSearchRequest,
    principal: DataPrincipal = Depends(
        require_data_access("trials:read", "clinicaltrials_gov")
    ),
):
    """Search trials using text, phase, status, date, result, and entity filters."""

    def worker():
        with get_cortellis_session() as session:
            return run_clinical_trial_search(session, request)

    return await _run_guarded_source_query(worker, principal)


@router.post("/search")
async def governed_federated_search(
    request: FederatedSearchRequest,
    principal: DataPrincipal = Depends(
        require_data_access("data:read", "federated_search")
    ),
):
    """Search selected datasets and return source-grained attributed groups."""
    _assert_federated_datasets_enabled(request)
    return await _run_guarded_source_query(
        lambda: run_federated_search(request),
        principal,
    )


@router.get("/companies/{company_id}/dossier")
async def governed_company_dossier(
    company_id: int,
    principal: DataPrincipal = Depends(
        require_data_access("data:read", "federated_search")
    ),
):
    """Return an evidence-bounded company dossier across enabled datasets."""
    disabled = _disabled_datasets()
    if "integrated_companies" in disabled:
        raise HTTPException(
            status_code=403,
            detail="Dataset disabled by owner policy: integrated_companies",
        )
    result = await _run_guarded_source_query(
        lambda: build_company_dossier(
            company_id,
            disabled_datasets=disabled,
        ),
        principal,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return result


@router.get("/assets/{drug_id}/dossier")
async def governed_asset_dossier(
    drug_id: int,
    principal: DataPrincipal = Depends(
        require_data_access("data:read", "federated_search")
    ),
):
    """Return an evidence-bounded asset dossier across enabled datasets."""
    disabled = _disabled_datasets()
    if "integrated_drugs" in disabled:
        raise HTTPException(
            status_code=403,
            detail="Dataset disabled by owner policy: integrated_drugs",
        )
    result = await _run_guarded_source_query(
        lambda: build_asset_dossier(
            drug_id,
            disabled_datasets=disabled,
        ),
        principal,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return result


def _cancel_backend(pid: int) -> None:
    with get_cortellis_engine().connect().execution_options(
        isolation_level="AUTOCOMMIT"
    ) as connection:
        connection.execute(
            text("SELECT pg_cancel_backend(:pid)"),
            {"pid": pid},
        )


async def _run_disconnect_aware(worker, http_request: Request | None, state: dict):
    task = asyncio.create_task(run_in_threadpool(worker))
    if http_request is None:
        return await task
    while True:
        done, _pending = await asyncio.wait({task}, timeout=0.25)
        if done:
            return task.result()
        if await http_request.is_disconnected():
            pid = state.get("backend_pid")
            if pid:
                await run_in_threadpool(_cancel_backend, pid)
            try:
                await task
            except Exception:
                pass
            raise HTTPException(status_code=499, detail="Client disconnected")


async def _advanced_search(
    endpoint: str,
    search_request: AdvancedSearchRequest,
    http_request: Request | None,
    principal: DataPrincipal | None,
):
    state: dict[str, Any] = {}
    runner = (
        run_advanced_deal_search
        if endpoint == "deals"
        else run_advanced_asset_search
    )

    def worker():
        started = time.perf_counter()
        with advanced_search_guard(principal):
            with get_cortellis_session() as session:
                try:
                    state["backend_pid"] = int(
                        session.execute(text("SELECT pg_backend_pid()")).scalar()
                    )
                except (AttributeError, TypeError):
                    # Lightweight test doubles do not expose a real backend.
                    pass
                result = runner(
                    session,
                    search_request,
                    allow_public_biology=_public_biology_allowed(),
                )
        logger.info(
            "advanced_search_complete",
            endpoint=endpoint,
            principal_type=getattr(principal, "principal_type", None),
            principal_id=getattr(principal, "principal_id", None),
            query_hash=result.get("query_hash"),
            filter_categories=result.get("matched_filter_categories"),
            expanded=result.get("expanded"),
            include_total=search_request.include_total,
            items=len(result.get("items", [])),
            elapsed_seconds=round(time.perf_counter() - started, 3),
        )
        return result

    try:
        return await _run_disconnect_aware(worker, http_request, state)
    except SearchRateLimited as exc:
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": "60"},
        ) from exc
    except SearchBusy as exc:
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": "5"},
        ) from exc
    except DBAPIError as exc:
        code = getattr(exc.orig, "pgcode", None) or getattr(
            exc.orig, "sqlstate", None
        )
        if code == "57014":
            raise HTTPException(
                status_code=504,
                detail="Search exceeded the 25-second execution limit",
            ) from exc
        logger.error(
            "advanced_search_database_error",
            endpoint=endpoint,
            error_type=type(exc.orig).__name__,
        )
        raise HTTPException(
            status_code=503,
            detail="Search database is temporarily unavailable",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/deals/search")
async def advanced_deal_search(
    request: AdvancedSearchRequest,
    http_request: Request = None,
    _principal: DataPrincipal = Depends(
        require_data_access("deals:read", "cortellis_deals")
    ),
):
    """Search deals using typed Boolean, date, evidence, and value filters."""
    return await _advanced_search("deals", request, http_request, _principal)


@router.post("/assets/search")
async def advanced_asset_search(
    request: AdvancedSearchRequest,
    http_request: Request = None,
    _principal: DataPrincipal = Depends(
        require_data_access("deals:read", "cortellis_deals")
    ),
):
    """Search deal-referenced assets with asset- and deal-attributed evidence."""
    return await _advanced_search("assets", request, http_request, _principal)


@router.get("/deals/{deal_id}")
async def deal_detail(
    deal_id: int,
    _principal: DataPrincipal = Depends(
        require_data_access("deals:read", "cortellis_deals")
    ),
):
    """Return a normalized deal with its source-backed related entities."""
    with get_cortellis_session() as session:
        deal = (
            session.execute(
                text("""
            SELECT deal.*, finance.*
            FROM deals deal
            LEFT JOIN deal_finance_summary finance ON finance.deal_id=deal.id
            WHERE deal.id=:deal_id
        """),
                {"deal_id": deal_id},
            )
            .mappings()
            .first()
        )
        if not deal:
            raise HTTPException(status_code=404, detail="Deal not found")
        relationships = {}
        queries = {
            "companies": """
                SELECT company.id, company.name, company.company_type, link.role
                FROM deal_companies link JOIN companies company
                  ON company.id=link.company_id
                WHERE link.deal_id=:deal_id ORDER BY link.role, company.name
            """,
            "drugs": """
                SELECT drug.* FROM deal_drugs link JOIN drugs drug
                  ON drug.id=link.drug_id
                WHERE link.deal_id=:deal_id ORDER BY drug.name_display
            """,
            "indications": """
                SELECT indication.id, indication.name, link.is_principal
                FROM deal_indications link JOIN indications indication
                  ON indication.id=link.indication_id
                WHERE link.deal_id=:deal_id ORDER BY link.is_principal DESC,
                     indication.name
            """,
            "actions": """
                SELECT action.id, action.name, link.action_type
                FROM deal_actions link JOIN actions action ON action.id=link.action_id
                WHERE link.deal_id=:deal_id ORDER BY link.action_type, action.name
            """,
            "technologies": """
                SELECT technology.id, technology.name, link.is_principal
                FROM deal_technologies link JOIN technologies technology
                  ON technology.id=link.technology_id
                WHERE link.deal_id=:deal_id ORDER BY link.is_principal DESC,
                     technology.name
            """,
            "territories": """
                SELECT territory.id, territory.name, link.territory_type
                FROM deal_territories link JOIN territories territory
                  ON territory.id=link.territory_id
                WHERE link.deal_id=:deal_id ORDER BY link.territory_type,
                     territory.name
            """,
            "patents": """
                SELECT patent.id, patent.number, patent.title
                FROM deal_patents link JOIN patents patent ON patent.id=link.patent_id
                WHERE link.deal_id=:deal_id ORDER BY patent.number
            """,
            "timeline": """
                SELECT id, event_date, event_type, stage, stage_notes, summary,
                       payments_to_principal, payments_to_partner, drugs
                FROM deal_timeline_events WHERE deal_id=:deal_id
                ORDER BY event_date, id
            """,
            "contracts": """
                SELECT id, contract_types, has_pdf, has_text, date_filing,
                       date_contract, is_redacted
                FROM deal_contracts WHERE deal_id=:deal_id
                ORDER BY date_contract, id
            """,
            "sources": """
                SELECT source_id, source_type, first_seen_at, last_seen_at
                FROM cortellis_deal_sources
                WHERE deal_id=:deal_id AND is_current=TRUE
                ORDER BY source_type, source_id
            """,
        }
        for name, sql in queries.items():
            rows = session.execute(text(sql), {"deal_id": deal_id}).mappings().all()
            relationships[name] = [dict(row) for row in rows]
    result = dict(deal)
    result.update(relationships)
    return result


@router.get("/financial-terms")
async def list_financial_terms(
    after_id: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    deal_id: int | None = Query(default=None, ge=1),
    term_type: str | None = Query(default=None, max_length=100),
    basis: str | None = Query(default=None, max_length=100),
    disclosure_status: str | None = Query(default=None, max_length=100),
    min_amount_usd_millions: float | None = Query(default=None, ge=0),
    min_rate_pct: float | None = Query(default=None, ge=0, le=100),
    _principal: DataPrincipal = Depends(
        require_data_access("deals:read", "cortellis_deals")
    ),
):
    """Cursor-page normalized Cortellis financial terms with provenance."""
    filters = [
        "term.id > :after_id",
        "term.parser_version = :parser_version",
    ]
    params: dict[str, Any] = {
        "after_id": after_id,
        "limit": limit + 1,
        "parser_version": FINANCE_PARSER_VERSION,
    }
    for field, value in (
        ("deal_id", deal_id),
        ("term_type", term_type),
        ("basis", basis),
        ("disclosure_status", disclosure_status),
    ):
        if value is not None:
            filters.append(f"term.{field} = :{field}")
            params[field] = value
    if min_amount_usd_millions is not None:
        filters.append("term.amount_usd_millions >= :min_amount_usd_millions")
        params["min_amount_usd_millions"] = min_amount_usd_millions
    if min_rate_pct is not None:
        filters.append(
            "GREATEST(term.rate_min_pct, term.rate_max_pct) >= :min_rate_pct"
        )
        params["min_rate_pct"] = min_rate_pct
    with get_cortellis_session() as session:
        rows = (
            session.execute(
                text(f"""
            SELECT term.id, term.deal_id, deal.title AS deal_title,
                   term.recipient, term.basis, term.term_type,
                   term.source_payment_type, term.payment_date,
                   term.amount_reported_millions, term.reported_currency,
                   term.reported_unit, term.amount_usd_millions,
                   term.rate_min_pct, term.rate_max_pct, term.accuracy,
                   term.disclosure_status, term.note, term.is_breakdown,
                   term.confidence, term.source_path, term.source_hash,
                   term.parser_version, term.extracted_at
            FROM deal_financial_terms term
            JOIN deals deal ON deal.id=term.deal_id
            WHERE {" AND ".join(filters)}
            ORDER BY term.id
            LIMIT :limit
        """),
                params,
            )
            .mappings()
            .all()
        )
    return _page([dict(row) for row in rows], limit, "id")


@router.get("/companies")
async def list_companies(
    after_id: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    query: str | None = Query(default=None, max_length=200),
    _principal: DataPrincipal = Depends(
        require_data_access("companies:read", "integrated_companies")
    ),
):
    """Cursor-page companies referenced by Cortellis deals."""
    where = "company.id > :after_id"
    params: dict[str, Any] = {"after_id": after_id, "limit": limit + 1}
    if query:
        where += " AND company.name ILIKE :query"
        params["query"] = f"%{query}%"
    with get_cortellis_session() as session:
        rows = (
            session.execute(
                text(f"""
            SELECT company.id, company.name, company.company_type,
                   company.hq_location,
                   COUNT(DISTINCT link.deal_id) AS deal_count,
                   COALESCE((SELECT jsonb_agg(jsonb_build_object(
                       'type', identifier.identifier_type,
                       'value', identifier.identifier_value,
                       'source', identifier.source,
                       'review_status', identifier.review_status
                   ) ORDER BY identifier.identifier_type)
                   FROM company_identifiers identifier
                   WHERE identifier.company_id=company.id), '[]'::jsonb)
                     AS identifiers
            FROM companies company
            LEFT JOIN deal_companies link ON link.company_id=company.id
            WHERE {where}
            GROUP BY company.id
            ORDER BY company.id
            LIMIT :limit
        """),
                params,
            )
            .mappings()
            .all()
        )
    return _page([dict(row) for row in rows], limit, "id")


def _company_intelligence_or_404(company_id: int) -> dict[str, Any]:
    with get_cortellis_session() as session:
        result = company_asset_intelligence(session, company_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return result


@router.get("/companies/{company_id}/oncology-assets")
async def company_oncology_assets(
    company_id: int,
    _principal: DataPrincipal = Depends(
        require_data_access("deals:read", "cortellis_deals")
    ),
):
    """Return deal-referenced oncology biologics, modalities, and indications."""
    result = _company_intelligence_or_404(company_id)
    return {
        **result["oncology_assets"],
        "deal_records_considered": result["deal_records_considered"],
        "scope_truncated": result["scope_truncated"],
    }


@router.get("/companies/{company_id}/asset-rights")
async def company_asset_rights(
    company_id: int,
    _principal: DataPrincipal = Depends(
        require_data_access("deals:read", "cortellis_deals")
    ),
):
    """Return observed license scope without inferring current legal ownership."""
    result = _company_intelligence_or_404(company_id)
    return {
        **result["asset_rights"],
        "deal_records_considered": result["deal_records_considered"],
        "scope_truncated": result["scope_truncated"],
    }


@router.get("/companies/{company_id}/manufacturing-relationships")
async def company_manufacturing_relationships(
    company_id: int,
    _principal: DataPrincipal = Depends(
        require_data_access("deals:read", "cortellis_deals")
    ),
):
    """Return manufacturing/CDMO relationships and conservative US-site status."""
    result = _company_intelligence_or_404(company_id)
    return {
        **result["manufacturing_relationships"],
        "deal_records_considered": result["deal_records_considered"],
        "scope_truncated": result["scope_truncated"],
    }


@router.get("/drugs")
async def list_drugs(
    after_id: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    query: str | None = Query(default=None, max_length=200),
    _principal: DataPrincipal = Depends(
        require_data_access("drugs:read", "integrated_drugs")
    ),
):
    """Cursor-page deal assets with public identifiers when available."""
    where = "drug.id > :after_id"
    params: dict[str, Any] = {"after_id": after_id, "limit": limit + 1}
    if query:
        where += " AND (drug.name_display ILIKE :query OR EXISTS (SELECT 1 "
        where += "FROM drug_aliases alias WHERE alias.drug_id=drug.id "
        where += "AND alias.alias_value ILIKE :query))"
        params["query"] = f"%{query}%"
    with get_cortellis_session() as session:
        rows = (
            session.execute(
                text(f"""
            SELECT drug.id, drug.name_display, drug.phase_highest_start,
                   drug.phase_highest_now,
                   COUNT(DISTINCT deal_link.deal_id) AS deal_count,
                   COALESCE((SELECT jsonb_agg(jsonb_build_object(
                       'type', identifier.identifier_type,
                       'value', identifier.identifier_value,
                       'source', identifier.source,
                       'review_status', identifier.review_status
                   ) ORDER BY identifier.identifier_type)
                   FROM drug_identifiers identifier
                   WHERE identifier.drug_id=drug.id), '[]'::jsonb)
                     AS identifiers
            FROM drugs drug
            LEFT JOIN deal_drugs deal_link ON deal_link.drug_id=drug.id
            WHERE {where}
            GROUP BY drug.id
            ORDER BY drug.id
            LIMIT :limit
        """),
                params,
            )
            .mappings()
            .all()
        )
    return _page([dict(row) for row in rows], limit, "id")


@router.get("/clinical-trials")
async def list_trials(
    after_nct_id: str = Query(default="", max_length=11),
    limit: int = Query(default=50, ge=1, le=100),
    status: str | None = Query(default=None, max_length=50),
    drug_id: int | None = None,
    company_id: int | None = None,
    _principal: DataPrincipal = Depends(
        require_data_access("trials:read", "clinicaltrials_gov")
    ),
):
    """Cursor-page current ClinicalTrials.gov records and exact entity links."""
    filters = ["trial.nct_id > :after_nct_id"]
    params: dict[str, Any] = {"after_nct_id": after_nct_id, "limit": limit + 1}
    if status:
        filters.append("trial.overall_status=:status")
        params["status"] = status.upper()
    if drug_id is not None:
        filters.append(
            "EXISTS (SELECT 1 FROM clinical_trial_drugs link WHERE "
            "link.nct_id=trial.nct_id AND link.drug_id=:drug_id)"
        )
        params["drug_id"] = drug_id
    if company_id is not None:
        filters.append(
            "EXISTS (SELECT 1 FROM clinical_trial_companies link WHERE "
            "link.nct_id=trial.nct_id AND link.company_id=:company_id)"
        )
        params["company_id"] = company_id
    with get_cortellis_session() as session:
        rows = (
            session.execute(
                text(f"""
            SELECT trial.nct_id, trial.brief_title, trial.official_title,
                   trial.overall_status, trial.phases, trial.study_type,
                   trial.enrollment, trial.start_date,
                   trial.primary_completion_date, trial.completion_date,
                   trial.last_update_posted, trial.lead_sponsor_name,
                   trial.conditions, trial.interventions, trial.has_results,
                   trial.source_url
            FROM clinical_trials trial
            WHERE {" AND ".join(filters)}
            ORDER BY trial.nct_id
            LIMIT :limit
        """),
                params,
            )
            .mappings()
            .all()
        )
    return _page([dict(row) for row in rows], limit, "nct_id")


@router.get("/biology/targets")
async def list_targets(
    after_id: str = Query(default="", max_length=30),
    limit: int = Query(default=50, ge=1, le=100),
    query: str | None = Query(default=None, max_length=200),
    _principal: DataPrincipal = Depends(
        require_data_access("biology:read", "public_biology")
    ),
):
    """Cursor-page Open Targets concepts with exact linked-drug counts."""
    where = "target.ensembl_id > :after_id"
    params: dict[str, Any] = {"after_id": after_id, "limit": limit + 1}
    if query:
        where += " AND (target.approved_symbol ILIKE :query OR "
        where += "target.approved_name ILIKE :query)"
        params["query"] = f"%{query}%"
    with get_cortellis_session() as session:
        rows = (
            session.execute(
                text(f"""
            SELECT target.ensembl_id, target.approved_symbol,
                   target.approved_name, target.biotype, target.protein_ids,
                   target.source, target.source_version,
                   COUNT(DISTINCT link.drug_id) AS linked_drugs
            FROM public_targets target
            LEFT JOIN public_drug_target_links link
              ON link.ensembl_id=target.ensembl_id
            WHERE {where}
            GROUP BY target.ensembl_id
            ORDER BY target.ensembl_id
            LIMIT :limit
        """),
                params,
            )
            .mappings()
            .all()
        )
    return _page([dict(row) for row in rows], limit, "ensembl_id")


@router.get("/biology/diseases")
async def list_diseases(
    after_id: str = Query(default="", max_length=100),
    limit: int = Query(default=50, ge=1, le=100),
    query: str | None = Query(default=None, max_length=200),
    _principal: DataPrincipal = Depends(
        require_data_access("biology:read", "public_biology")
    ),
):
    """Cursor-page disease concepts and exact linked-drug counts."""
    where = "disease.disease_id > :after_id"
    params: dict[str, Any] = {"after_id": after_id, "limit": limit + 1}
    if query:
        where += " AND disease.name ILIKE :query"
        params["query"] = f"%{query}%"
    with get_cortellis_session() as session:
        rows = (
            session.execute(
                text(f"""
            SELECT disease.disease_id, disease.name, disease.source,
                   disease.source_version,
                   COUNT(DISTINCT link.drug_id) AS linked_drugs
            FROM public_diseases disease
            LEFT JOIN public_drug_disease_links link
              ON link.disease_id=disease.disease_id
            WHERE {where}
            GROUP BY disease.disease_id
            ORDER BY disease.disease_id
            LIMIT :limit
        """),
                params,
            )
            .mappings()
            .all()
        )
    return _page([dict(row) for row in rows], limit, "disease_id")


@router.get("/edgar/documents")
async def list_edgar_documents(
    after_id: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    form: str | None = Query(default=None, max_length=30),
    cik: str | None = Query(default=None, max_length=20),
    _principal: DataPrincipal = Depends(
        require_data_access("sources:read", "sec_edgar")
    ),
):
    """Cursor-page SEC filing metadata with source URLs and company identity."""
    filters = ["document.id > :after_id"]
    params: dict[str, Any] = {"after_id": after_id, "limit": limit + 1}
    if form:
        filters.append("document.subtype=:form")
        params["form"] = form
    if cik:
        filters.append("company.cik=:cik")
        params["cik"] = cik.strip().zfill(10)
    with get_edgar_session() as session:
        rows = (
            session.execute(
                text(f"""
            SELECT document.id, document.doc_type, document.subtype,
                   document.title, document.published_at, document.accession_no,
                   document.parse_ok, raw.url AS source_url, raw.filing_date,
                   company.cik, company.ticker, company.name AS company_name
            FROM documents document
            JOIN raw_documents raw ON raw.id=document.raw_document_id
            LEFT JOIN companies company ON company.id=raw.company_id
            WHERE {" AND ".join(filters)}
            ORDER BY document.id
            LIMIT :limit
        """),
                params,
            )
            .mappings()
            .all()
        )
    return _page([dict(row) for row in rows], limit, "id")


@router.get("/source-status")
async def source_status(
    _principal: DataPrincipal = Depends(
        require_data_access("sources:read", "source_status")
    ),
):
    """Return current monitored sync state without exposing credentials or errors."""
    with get_cortellis_session() as session:
        rows = (
            session.execute(
                text("""
            SELECT source_key, label, status, alert_status, last_success_at,
                   source_data_at, source_cursor, duration_seconds, counts
            FROM source_job_state ORDER BY source_key
        """)
            )
            .mappings()
            .all()
        )
    return {"sources": [dict(row) for row in rows]}
