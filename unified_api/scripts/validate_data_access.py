"""Read-only production-schema smoke test for the governed data API."""

from __future__ import annotations

import asyncio
import json

from unified_api.routers.data_access import (
    data_catalog,
    deal_detail,
    list_companies,
    list_deals,
    list_diseases,
    list_drugs,
    list_edgar_documents,
    list_targets,
    list_trials,
    source_status,
)
from unified_api.services.api_credentials import DataPrincipal


async def validate() -> dict:
    """Execute one bounded query through every governed data handler."""
    principal = DataPrincipal(
        principal_type="system",
        principal_id="schema-smoke",
        name="schema-smoke",
        scopes=["data:read"],
    )
    catalog = await data_catalog(_principal=principal)
    deals = await list_deals(
        after_id=0,
        limit=2,
        query=None,
        company_id=None,
        drug_id=None,
        indication_id=None,
        _principal=principal,
    )
    detail = await deal_detail(
        deals["items"][0]["id"], _principal=principal
    )
    companies = await list_companies(
        after_id=0, limit=2, query=None, _principal=principal
    )
    drugs = await list_drugs(
        after_id=0, limit=2, query=None, _principal=principal
    )
    trials = await list_trials(
        after_nct_id="",
        limit=2,
        status=None,
        drug_id=None,
        company_id=None,
        _principal=principal,
    )
    targets = await list_targets(
        after_id="", limit=2, query=None, _principal=principal
    )
    diseases = await list_diseases(
        after_id="", limit=2, query=None, _principal=principal
    )
    edgar = await list_edgar_documents(
        after_id=0,
        limit=2,
        form=None,
        cik=None,
        _principal=principal,
    )
    sources = await source_status(_principal=principal)
    return {
        "status": "passed",
        "catalog_sources": len(catalog["sources"]),
        "deal_rows": len(deals["items"]),
        "deal_detail_id": detail["id"],
        "company_rows": len(companies["items"]),
        "drug_rows": len(drugs["items"]),
        "trial_rows": len(trials["items"]),
        "target_rows": len(targets["items"]),
        "disease_rows": len(diseases["items"]),
        "edgar_rows": len(edgar["items"]),
        "monitored_sources": len(sources["sources"]),
    }


def main() -> None:
    print(json.dumps(asyncio.run(validate()), sort_keys=True))


if __name__ == "__main__":
    main()
